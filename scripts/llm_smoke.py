"""Opt-in live smoke test of the Claude provider: one decide, one ask, one intervention.

Makes 3 paid API calls. Never run in CI. Needs `uv sync --extra anthropic` and
ANTHROPIC_API_KEY (environment or .env).

    uv run python scripts/llm_smoke.py            # call and report
    uv run python scripts/llm_smoke.py --record   # also save replies as test fixtures
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for source in [
    "backend/api/src",
    *[f"backend/modules/{name}/src" for name in ["simulation", "agents", "history"]],
]:
    sys.path.insert(0, str(ROOT / source))

from kronos.config import Settings  # noqa: E402
from kronos_agents.anthropic_provider import DEFAULT_MODEL, AnthropicProvider  # noqa: E402
from kronos_agents.provider import AgentService, ProviderError  # noqa: E402
from kronos_sim.engine import Engine, InvalidAction  # noqa: E402
from kronos_sim.queries import observe  # noqa: E402
from kronos_sim.seed import initial_world  # noqa: E402

FIXTURES = ROOT / "backend/modules/agents/tests/fixtures/anthropic"


class RecordingClient:
    """Wraps AsyncAnthropic and keeps each raw response and request size."""

    def __init__(self, client):
        self.inner, self.calls = client, []
        self.beta = type("Beta", (), {"messages": type("M", (), {"create": self.create})()})()

    async def create(self, **kwargs):
        started = time.perf_counter()
        response = await self.inner.beta.messages.create(**kwargs)
        self.calls.append(
            {
                "seconds": round(time.perf_counter() - started, 2),
                "schema_bytes": len(json.dumps(kwargs["output_config"]["format"]["schema"])),
                "usage": response.usage.model_dump(mode="json"),
                "response": response.model_dump(mode="json"),
            }
        )
        return response


def involves(event, citizen_id: str) -> bool:
    return event.actor_id == citizen_id or citizen_id in json.dumps(
        event.payload.model_dump(mode="json")
    )


async def run(record: bool, model: str, timeout: float) -> int:
    key = Settings().anthropic_api_key
    if key is None:
        print("ANTHROPIC_API_KEY is not set (environment or .env).", file=sys.stderr)
        return 1
    import anthropic

    client = RecordingClient(
        anthropic.AsyncAnthropic(api_key=key.get_secret_value(), timeout=timeout, max_retries=0)
    )
    agents = AgentService(AnthropicProvider(model, client=client), timeout=timeout, retries=0)

    # A few days in, so the citizen has events to explain and needs to act on.
    world, events = initial_world(42), []
    for _ in range(3):
        result = Engine(world).tick()
        world, events = result.state, events + result.events
    citizen_id = "citizen-6"  # Finn: unemployed and poor, so the decision matters
    observation = observe(world, citizen_id)

    failures = 0
    print(f"Model {model}, citizen {citizen_id}, day {world.tick}\n")
    try:
        action = await agents.decide(observation)
        try:
            Engine(world).apply(action)
            verdict = "engine accepted"
        except InvalidAction as exc:
            verdict = f"engine rejected: {exc}"
        print(f"decide  -> {action.type}: {action.rationale!r} ({verdict})")
    except ProviderError as exc:
        failures += 1
        print(f"decide  -> FAILED: {exc}")
    try:
        own = [e for e in events if involves(e, citizen_id)][-20:]
        answer = await agents.ask("How have the last few days gone for you?", observation, own)
        print(f"ask     -> {answer.answer!r} cites {answer.cited_event_ids}")
    except ProviderError as exc:
        failures += 1
        print(f"ask     -> FAILED: {exc}")
    try:
        command = await agents.parse("Give 5 coins to everyone")
        print(f"interv. -> {command.model_dump(mode='json')}")
    except ProviderError as exc:
        failures += 1
        print(f"interv. -> FAILED: {exc}")

    print()
    for task, call in zip(["decision", "ask", "intervention"], client.calls, strict=False):
        usage = call["usage"]
        print(
            f"{task:<12} {call['seconds']:>5}s  schema {call['schema_bytes']:>6} B  "
            f"in {usage['input_tokens']} (+{usage.get('cache_read_input_tokens') or 0} cached)  "
            f"out {usage['output_tokens']}"
        )
        if record:
            path = FIXTURES / f"live_{task}.json"
            path.write_text(json.dumps(call["response"], indent=2) + "\n")
            print(f"{'':<12} recorded {path.relative_to(ROOT)}")
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--record", action="store_true", help="save replies as test fixtures")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args.record, args.model, args.timeout)))


if __name__ == "__main__":
    main()
