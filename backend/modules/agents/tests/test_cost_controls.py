"""Phase 5 cost controls: response cache, debug log, call budget, concurrency, tiers."""

import asyncio
import json

import pytest
from kronos_agents.fallback import UtilityPolicy
from kronos_agents.middleware import CachingProvider, LoggingProvider, cache_key
from kronos_agents.provider import AgentService, MockProvider, ProviderError
from kronos_sim.queries import observe
from kronos_sim.seed import initial_world


class CountingProvider(MockProvider):
    """The mock's answers, counting calls and peak concurrency; reports itself as `llm`."""

    source = "llm"

    def __init__(self, delay: float = 0):
        self.calls, self.in_flight, self.peak, self.delay = 0, 0, 0, delay

    async def complete(self, task, observation):
        self.calls += 1
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
            return await super().complete(task, observation)
        finally:
            self.in_flight -= 1


class Broken:
    async def complete(self, task, observation):
        raise AssertionError("must not be called")


def every_day(**kwargs) -> AgentService:
    """Everyone decides every tick (round of 1), so tests see all citizens at once."""
    return AgentService(kwargs.pop("provider"), round_ticks=1, fallback=UtilityPolicy(), **kwargs)


def observation(citizen="citizen-6"):
    return observe(initial_world(42), citizen).model_dump(mode="json")


# --- cache ---------------------------------------------------------------------------


def test_cache_answers_repeat_calls_without_the_provider(tmp_path):
    inner = CountingProvider()
    cache = CachingProvider(inner, tmp_path, tag="model:v1")
    first = asyncio.run(cache.complete("decision", observation()))
    again = asyncio.run(cache.complete("decision", observation()))
    assert first == again and inner.calls == 1 and (cache.hits, cache.misses) == (1, 1)
    assert cache.source == "llm"


def test_cache_key_ignores_branch_but_not_state_or_tag():
    base = observation()
    forked = {**base, "branch_id": "fork-a"}
    later = {**base, "sequence": base["sequence"] + 1}
    assert cache_key("decision", base, "t") == cache_key("decision", forked, "t")
    assert cache_key("decision", base, "t") != cache_key("decision", later, "t")
    assert cache_key("decision", base, "t") != cache_key("decision", base, "other-prompts")
    assert cache_key("decision", base, "t") != cache_key("ask", base, "t")


def test_replay_only_cache_never_calls_the_provider(tmp_path):
    cache = CachingProvider(Broken(), tmp_path, replay_only=True)
    with pytest.raises(ProviderError, match="replay-only"):
        asyncio.run(cache.complete("decision", observation()))
    # Through AgentService a miss becomes a fallback decision, never a stall.
    service = AgentService(cache, fallback=UtilityPolicy())
    proposal = asyncio.run(service.proposal(observe(initial_world(42), "citizen-6")))
    assert proposal.source == "fallback"


def test_cache_skips_output_that_is_not_json(tmp_path):
    class Garbage:
        async def complete(self, task, observation):
            return "not json"

    cache = CachingProvider(Garbage(), tmp_path)
    assert asyncio.run(cache.complete("decision", observation())) == "not json"
    assert not any(tmp_path.rglob("*.json"))


# --- debug log -----------------------------------------------------------------------


def test_log_records_replies_and_errors(tmp_path):
    path = tmp_path / "llm.jsonl"
    asyncio.run(LoggingProvider(MockProvider(), path).complete("decision", observation()))
    with pytest.raises(AssertionError):
        asyncio.run(LoggingProvider(Broken(), path).complete("decision", observation()))
    first, second = (json.loads(line) for line in path.read_text().splitlines())
    assert first["task"] == "decision" and json.loads(first["reply"])["actor_id"] == "citizen-6"
    assert second["error"].startswith("AssertionError") and "reply" not in second
    assert first["observation"]["citizen"]["id"] == "citizen-6"


# --- budget, concurrency and tiers -----------------------------------------------------


def test_call_budget_sends_the_rest_to_the_fallback():
    provider = CountingProvider()
    world = initial_world(42)
    actions = asyncio.run(every_day(provider=provider, calls_per_tick=2).propose(world))
    assert provider.calls == 2
    assert len(actions) == len(world.citizens)
    sources = sorted(a.rationale.split("]")[0] + "]" for a in actions)
    assert sources.count("[llm]") == 2 and sources.count("[fallback]") == len(actions) - 2


def test_zero_budget_never_calls_the_provider():
    actions = asyncio.run(every_day(provider=Broken(), calls_per_tick=0).propose(initial_world(42)))
    assert actions and all(a.rationale.startswith("[fallback]") for a in actions)


def test_concurrency_cap_limits_calls_in_flight():
    provider = CountingProvider(delay=0.01)
    asyncio.run(every_day(provider=provider, concurrency=2).propose(initial_world(42)))
    assert provider.calls == 7 and provider.peak == 2


def test_tiers_owners_first_then_by_id():
    world = initial_world(42)
    service = every_day(provider=CountingProvider(), strategic_limit=4)
    # Elena, Marcus and Ada own the businesses; then citizen-3 by ID.
    assert service.strategic(world) == {"citizen-0", "citizen-1", "citizen-2", "citizen-3"}
    provider = service.provider
    asyncio.run(service.propose(world))
    assert provider.calls == 4


def test_explicit_strategic_list_wins_and_ignores_unknown_ids():
    world = initial_world(42)
    service = every_day(provider=CountingProvider(), strategic_ids=["citizen-6", "ghost"])
    assert service.strategic(world) == {"citizen-6"}


def test_without_a_fallback_non_strategic_citizens_skip_their_turn():
    provider = CountingProvider()
    service = AgentService(provider, round_ticks=1, strategic_limit=2)
    actions = asyncio.run(service.propose(initial_world(42)))
    assert provider.calls == 2 and len(actions) == 2
