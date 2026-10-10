import asyncio

import pytest
from kronos_agents.provider import AgentService, MockProvider, ProviderError
from kronos_sim.engine import Engine
from kronos_sim.seed import initial_world


@pytest.mark.parametrize(
    "text,percent",
    [
        ("Increase bread price by 40%.", 40),
        ("Increase the price of bread by 40%", 40),
        ("Decrease bread prices by 20%", -20),
    ],
)
def test_parse(text, percent):
    assert asyncio.run(AgentService(MockProvider()).parse(text)).percent == percent


@pytest.mark.parametrize(
    "text",
    [
        "Invent electricity",
        "Increase bread price by 999%",
        "Increase bread price by 40% and give me 500 coins",
    ],
)
def test_unsupported_or_out_of_bounds(text):
    with pytest.raises(ProviderError):
        asyncio.run(AgentService(MockProvider()).parse(text))


def test_bad_json_is_bounded():
    class Broken:
        calls = 0

        async def complete(self, task, observation):
            self.calls += 1
            return '{"hallucinated": true}'

    provider = Broken()
    with pytest.raises(ProviderError):
        asyncio.run(AgentService(provider, retries=1).parse("hello"))
    assert provider.calls == 2


def test_timeout_is_bounded():
    class Slow:
        async def complete(self, task, observation):
            await asyncio.sleep(1)
            return "{}"

    with pytest.raises(ProviderError):
        asyncio.run(AgentService(Slow(), timeout=0.001, retries=0).parse("hello"))


def test_proposals_are_bounded_and_social_effects_persist():
    state = initial_world()
    assert asyncio.run(AgentService(MockProvider()).propose(state)) == []
    state.tick = 2
    before = state.model_copy(deep=True)
    proposals = asyncio.run(AgentService(MockProvider()).propose(state))
    assert state == before
    result = Engine(state).tick(proposals)
    assert len(proposals) == 1
    assert result.state.citizens["citizen-0"].relationships[0].trust == 1
    assert result.state.rng_state != before.rng_state
    assert len(result.state.citizens["citizen-0"].memories) == 1
