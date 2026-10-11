"""GeminiProvider against a fake client: no network, no key, no SDK."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from kronos_agents.gemini_provider import DEFAULT_MODEL, PLAYER_MODEL, GeminiProvider
from kronos_agents.provider import AgentService, ProviderError
from kronos_sim.queries import observe
from kronos_sim.seed import initial_world


def _reply(*parts, finish="STOP"):
    content = SimpleNamespace(parts=[SimpleNamespace(thought=None, **p) for p in parts])
    return SimpleNamespace(
        candidates=[SimpleNamespace(content=content, finish_reason=SimpleNamespace(name=finish))]
    )


def _text(text, finish="STOP"):
    return _reply({"text": text, "function_call": None}, finish=finish)


class FakeClient:
    """Mimics `genai.Client().aio.models.generate_content`, recording each request."""

    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self.generate))

    async def generate(self, **kwargs):
        self.requests.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _observation(citizen="citizen-5"):
    state = initial_world(42)
    state.citizens[citizen].inventory.bread = 0
    return observe(state, citizen)


def test_decision_uses_the_cheap_model_and_validates():
    obs = _observation()
    reply = {
        "result": {
            "type": "apply_job",
            "actor_id": "citizen-5",
            "building_id": "farm",
            "rationale": "I need work.",
        }
    }
    client = FakeClient(_text(json.dumps(reply)))
    service = AgentService(GeminiProvider(client=client), retries=0, fallback=None)
    action = asyncio.run(service.decide(obs))
    assert action.type == "apply_job"
    request = client.requests[0]
    assert request["model"] == DEFAULT_MODEL
    assert request["config"]["response_mime_type"] == "application/json"


def test_long_menus_put_the_schema_in_the_prompt():
    obs = _observation()
    obs.available_actions = [
        "buy", "sell", "trade", "lend", "interact",
        "communicate", "apply_job", "move_to", "consume", "adjust_goals",
    ]  # fmt: skip
    kwargs, wrapped = GeminiProvider(client=FakeClient()).request("decision", obs.model_dump())
    assert "response_json_schema" not in kwargs["config"] and not wrapped
    assert "matching this schema" in kwargs["contents"]
    obs.available_actions = obs.available_actions[:3]
    kwargs, wrapped = GeminiProvider(client=FakeClient()).request("decision", obs.model_dump())
    assert "response_json_schema" in kwargs["config"] and wrapped


def test_player_calls_use_the_player_model_and_function_calling():
    call = SimpleNamespace(name="grant_money", args={"amount": 500})
    client = FakeClient(_reply({"text": None, "function_call": call}))
    provider = GeminiProvider(client=client)
    name, args, _ = asyncio.run(provider.choose_tool("Give 5 coins to everyone", {}))
    assert (name, args) == ("grant_money", {"amount": 500})
    config = client.requests[0]["config"]
    assert client.requests[0]["model"] == PLAYER_MODEL
    names = {d["name"] for d in config["tools"][0]["function_declarations"]}
    assert "grant_money" in names
    assert provider.request("ask", _observation().model_dump())[0]["model"] == PLAYER_MODEL


def test_a_plain_reply_means_no_tool():
    client = FakeClient(_text("I am the voice of Oakhaven."))
    name, args, text = asyncio.run(GeminiProvider(client=client).choose_tool("hello", {}))
    assert name is None and args == {} and text == "I am the voice of Oakhaven."


def test_failures_become_provider_errors_without_the_key():
    error = type("ClientError", (Exception,), {})("bad key AIza-secret")
    error.code, error.message = 403, "API key not valid"
    client = FakeClient(error, _text("{}", finish="SAFETY"))
    provider = GeminiProvider(client=client)
    with pytest.raises(ProviderError, match="GEMINI_API_KEY") as caught:
        asyncio.run(provider.complete("decision", _observation().model_dump()))
    assert "AIza" not in str(caught.value)
    with pytest.raises(ProviderError, match="declined"):
        asyncio.run(provider.complete("decision", _observation().model_dump()))
