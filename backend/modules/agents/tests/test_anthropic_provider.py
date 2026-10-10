"""AnthropicProvider against recorded responses and a fake client: no network, no key, no SDK."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from kronos_agents.anthropic_provider import DEFAULT_MODEL, AnthropicProvider, output_schema
from kronos_agents.prompts import decision_examples, system_prompt
from kronos_agents.provider import AgentService, ProviderError
from kronos_sim.engine import Engine
from kronos_sim.models import AgentAction
from kronos_sim.queries import observe
from kronos_sim.seed import initial_world
from pydantic import TypeAdapter

FIXTURES = Path(__file__).parent / "fixtures" / "anthropic"


def _ns(value):
    if isinstance(value, dict):
        return SimpleNamespace(**{k: _ns(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_ns(v) for v in value]
    return value


def recorded(name: str, **replace: str):
    text = (FIXTURES / name).read_text()
    for old, new in replace.items():
        text = text.replace(old, new)
    return _ns(json.loads(text))


class FakeClient:
    """Mimics `AsyncAnthropic().beta.messages.create`, recording each request."""

    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def hungry_world():
    state = initial_world(42)
    state.citizens["citizen-5"].inventory.bread = 0
    return state


def test_request_shape_for_a_decision():
    client = FakeClient(recorded("decision_buy.json"))
    provider = AnthropicProvider(client=client)
    observation = observe(hungry_world(), "citizen-5")
    asyncio.run(AgentService(provider).decide(observation))

    (request,) = client.requests
    assert request["model"] == DEFAULT_MODEL == "claude-opus-5-5"
    assert request["fallbacks"] == "default"
    assert request["betas"] == ["server-side-fallback-2026-07-01"]
    assert "tool_choice" not in request  # forced tool use is a 400 on Opus 5.5
    (system,) = request["system"]
    assert system["text"] == system_prompt("decision")
    assert system["cache_control"] == {"type": "ephemeral"}
    assert "available_actions" in system["text"] and "rationale" in system["text"]
    (message,) = request["messages"]
    assert message["role"] == "user" and '"citizen-5"' in message["content"]

    fmt = request["output_config"]["format"]
    assert fmt["type"] == "json_schema" and request["output_config"]["effort"] == "low"
    schema = fmt["schema"]
    assert schema["required"] == ["result"] and schema["additionalProperties"] is False
    variants = schema["properties"]["result"]["anyOf"]
    assert len(variants) == len(observation.available_actions)
    buy = schema["$defs"]["Buy"]
    assert {"type", "rationale", "actor_id"} <= set(buy["required"])
    assert buy["properties"]["rationale"] == {
        "type": "string",
        "description": buy["properties"]["rationale"]["description"],
    }
    assert buy["properties"]["type"]["enum"] == ["buy"]


def test_schema_is_supported_by_structured_outputs():
    observation = observe(initial_world(42), "citizen-6").model_dump(mode="json")
    unsupported = {"minimum", "maximum", "exclusiveMinimum", "minLength", "maxLength", "oneOf"}

    def walk(node):
        if isinstance(node, dict):
            assert not unsupported & set(node), node
            assert "discriminator" not in node and "const" not in node
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for task, obs in [("decision", observation), ("ask", observation), ("intervention", {})]:
        schema, _ = output_schema(task, obs)
        assert schema["type"] == "object"
        walk(schema)


def test_decision_schema_is_narrowed_to_available_actions():
    observation = observe(initial_world(42), "citizen-6").model_dump(mode="json")
    observation["available_actions"] = ["consume", "buy"]
    schema, wrapped = output_schema("decision", observation)
    refs = [v["$ref"] for v in schema["properties"]["result"]["anyOf"]]
    assert wrapped and refs == ["#/$defs/Consume", "#/$defs/Buy"]
    assert "Sell" not in schema["$defs"]
    observation["available_actions"] = ["teleport"]
    with pytest.raises(ProviderError):
        output_schema("decision", observation)


def test_few_shot_examples_are_real_actions():
    examples = decision_examples()
    assert 2 <= len(examples) <= 4
    for example in examples:
        action = TypeAdapter(AgentAction).validate_json(example.split("Action:\n")[1])
        assert action.rationale


def test_end_to_end_decide_applies_through_the_engine():
    state = hungry_world()
    client = FakeClient(recorded("decision_buy.json"))
    action = asyncio.run(
        AgentService(AnthropicProvider(client=client)).decide(observe(state, "citizen-5"))
    )
    assert (action.type, action.building_id, action.actor_id) == ("buy", "bakery", "citizen-5")
    assert "I have no bread" in action.rationale  # AgentService may tag the source
    result = Engine(state).apply(action)
    assert result.state.citizens["citizen-5"].inventory.bread == 1


def test_decision_for_another_citizen_is_refused():
    client = FakeClient(recorded("decision_other_citizen.json"))
    with pytest.raises(ProviderError):
        asyncio.run(
            AgentService(AnthropicProvider(client=client)).decide(
                observe(hungry_world(), "citizen-5")
            )
        )


def test_ask_parses_and_cites_given_events():
    state = hungry_world()
    action = TypeAdapter(AgentAction).validate_python(
        {
            "type": "buy",
            "actor_id": "citizen-5",
            "building_id": "bakery",
            "resource": "bread",
            "quantity": 1,
            "max_unit_price": 500,
        }
    )
    tick = Engine(state).apply(action)
    events = list(tick.events)
    client = FakeClient(recorded("ask.json", CITED_EVENT_ID=events[0].id))
    service = AgentService(AnthropicProvider(client=client))
    result = asyncio.run(service.ask("Why?", observe(tick.state, "citizen-5"), events))
    assert result.cited_event_ids == [events[0].id]
    request = client.requests[0]
    assert request["system"][0]["text"] == system_prompt("ask")
    assert request["output_config"]["format"]["schema"]["required"] == ["answer"]
    assert '"question":"Why?"' in request["messages"][0]["content"]


def test_intervention_parses():
    client = FakeClient(recorded("intervention.json"))
    command = asyncio.run(
        AgentService(AnthropicProvider(client=client)).parse("Make bread 40% dearer")
    )
    assert command.percent == 40
    schema = client.requests[0]["output_config"]["format"]["schema"]
    # The Intervention union is not an object, so the schema wraps it in {"result": ...}.
    assert schema["required"] == ["result"] and schema["additionalProperties"] is False
    price = schema["$defs"]["PriceIntervention"]
    assert {"$ref": "#/$defs/PriceIntervention"} in schema["properties"]["result"]["anyOf"]
    assert "percent" in price["required"] and price["additionalProperties"] is False


@pytest.mark.parametrize(
    "response,message",
    [
        (recorded("refusal.json"), "declined"),
        (recorded("max_tokens.json"), "output tokens"),
        (TimeoutError(), "timed out"),
        (ConnectionError("boom"), "ConnectionError"),
    ],
)
def test_failures_become_provider_errors(response, message):
    provider = AnthropicProvider(client=FakeClient(response))
    with pytest.raises(ProviderError, match=message):
        asyncio.run(provider.complete("intervention", {"text": "x"}))


def test_sdk_errors_are_mapped_without_leaking_the_key():
    anthropic = pytest.importorskip("anthropic")
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    errors = [
        (anthropic.APITimeoutError(request=request), "timed out"),
        (
            anthropic.AuthenticationError(
                "bad key sk-ant-secret", response=httpx2.Response(401, request=request), body=None
            ),
            "ANTHROPIC_API_KEY",
        ),
        (
            anthropic.RateLimitError(
                "slow down", response=httpx2.Response(429, request=request), body=None
            ),
            "rate limit",
        ),
        (
            anthropic.BadRequestError(
                "low credit",
                response=httpx2.Response(400, request=request),
                body={"error": {"message": "Your credit balance is too low"}},
            ),
            "credit balance is too low",
        ),
    ]
    for error, message in errors:
        provider = AnthropicProvider(client=FakeClient(error))
        with pytest.raises(ProviderError, match=message) as info:
            asyncio.run(provider.complete("intervention", {"text": "x"}))
        assert "sk-ant" not in str(info.value)


def test_missing_key_or_sdk_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="ANTHROPIC_API_KEY|uv sync --extra anthropic"):
        AnthropicProvider()
