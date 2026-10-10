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


def test_proposals_follow_the_schedule_and_social_effects_persist():
    state = initial_world()
    before = state.model_copy(deep=True)
    service = AgentService(MockProvider())
    # Day 1 is slot 1 of a 3-day round; only citizen-5 hashes to it.
    assert service.scheduled(state) == ["citizen-5"]
    proposals = asyncio.run(service.propose(state))
    assert state == before  # proposing reads a world, never mutates it or its RNG
    assert [(p.actor_id, p.type) for p in proposals] == [("citizen-5", "communicate")]
    result = Engine(state).tick(proposals)
    assert result.state.citizens["citizen-0"].relationships[0].trust == 1
    assert result.state.rng_state != before.rng_state
    assert len(result.state.citizens["citizen-0"].memories) == 1


def test_every_citizen_decides_exactly_once_per_round():
    state = initial_world()
    for round_ticks in (1, 2, 3, 5):
        service, seen = AgentService(MockProvider(), round_ticks=round_ticks), []
        for day in range(round_ticks):
            state.tick = 10 * round_ticks + day
            seen += service.scheduled(state)
        assert sorted(seen) == sorted(state.citizens)


def test_slots_are_stable_when_citizens_arrive_or_leave():
    state = initial_world()
    service = AgentService(MockProvider(), round_ticks=4)

    def slots(world):
        out = {}
        for day in range(4):
            world.tick = day
            out.update({c: day for c in service.scheduled(world)})
        return out

    original = slots(state)
    state.citizens["citizen-99"] = state.citizens["citizen-1"].model_copy(
        update={"id": "citizen-99"}
    )
    del state.citizens["citizen-3"]
    changed = slots(state)
    assert all(changed[c] == day for c, day in original.items() if c != "citizen-3")
    assert "citizen-99" in changed


def test_proposals_run_concurrently_and_failures_are_isolated():
    class Flaky:
        def __init__(self):
            self.active = self.peak = 0

        async def complete(self, task, observation):
            self.active += 1
            self.peak = max(self.peak, self.active)
            await asyncio.sleep(0.05)
            self.active -= 1
            if observation["citizen"]["id"] == "citizen-2":
                raise RuntimeError("provider exploded")
            if observation["citizen"]["id"] == "citizen-4":
                return "not json"
            return await MockProvider().complete(task, observation)

    state = initial_world()
    provider = Flaky()
    proposals = asyncio.run(AgentService(provider, retries=0, round_ticks=1).propose(state))
    assert provider.peak == len(state.citizens)
    actors = [p.actor_id for p in proposals]
    assert actors == sorted(set(state.citizens) - {"citizen-2", "citizen-4"})


def test_mock_decisions_follow_needs():
    from kronos_sim.queries import observe

    state = initial_world()
    service = AgentService(MockProvider())
    state.citizens["citizen-6"].hunger = 60
    assert asyncio.run(service.decide(observe(state, "citizen-6"))).type == "consume"
    state.citizens["citizen-6"].inventory.bread = 0
    action = asyncio.run(service.decide(observe(state, "citizen-6")))
    assert (action.type, action.building_id, action.max_unit_price) == ("buy", "bakery", 500)
    state.citizens["citizen-6"].money = 10
    action = asyncio.run(service.decide(observe(state, "citizen-6")))
    assert (action.type, action.recipient_id) == ("communicate", "citizen-0")


def test_ask_rejects_citations_outside_given_events():
    from kronos_sim.queries import observe

    class Liar:
        async def complete(self, task, observation):
            return '{"answer": "Because of the war", "cited_event_ids": ["main:999"]}'

    with pytest.raises(ProviderError):
        asyncio.run(AgentService(Liar()).ask("Why?", observe(initial_world(), "citizen-0"), []))


CITIZENS = {"citizen-2": "Ada", "citizen-6": "Finn"}


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Lower bread prices by 10%", {"type": "modify_price", "percent": -10}),
        ("Set wages to 2 coins", {"type": "set_wage", "wage": 200, "percent": None}),
        ("Raise wages by 20%.", {"type": "set_wage", "percent": 20, "wage": None}),
        ("Cut all wages by 10%", {"type": "set_wage", "percent": -10}),
        ("Give 5 coins to everyone", {"type": "grant_money", "amount": 500, "citizen_id": None}),
        ("Give 50 cents to Ada", {"type": "grant_money", "amount": 50, "citizen_id": "citizen-2"}),
        ("Take 3 coins from finn", {"type": "grant_money", "amount": -300}),
        ("Harvest boom!", {"type": "adjust_resource", "stock_change": 50}),
        ("A drought", {"type": "adjust_resource", "stock_change": -50}),
        ("Add 40 wheat to the fields", {"type": "adjust_resource", "stock_change": 40}),
        ("Set wheat regrowth to 3 per day", {"type": "adjust_resource", "regen_per_tick": 3}),
        ("Hold a feast", {"type": "adjust_hunger", "change": -30, "citizen_id": None}),
        ("Famine", {"type": "adjust_hunger", "change": 30}),
        ("Reduce hunger by 20 for Ada", {"type": "adjust_hunger", "citizen_id": "citizen-2"}),
        ("Set minimum wage to 2 coins", {"type": "set_policy", "kind": "min_wage", "value": 200}),
        ("Cap bread price at 6 coins", {"kind": "bread_price_cap", "value": 600}),
        ("Set market tax to 5%", {"kind": "market_tax", "value": 500}),
        ("Remove the market tax", {"kind": "market_tax", "value": 0}),
    ],
)
def test_mock_intervention_grammar(text, expected):
    command = asyncio.run(AgentService(MockProvider()).parse(text, CITIZENS))
    assert {key: getattr(command, key) for key in expected} == expected


@pytest.mark.parametrize(
    "text,message",
    [
        ("Give 5 coins to Zed", "Unknown citizen 'Zed'"),
        ("Make it rain gold", "'Harvest boom'"),
        ("Set market tax to 500%", "Provider returned invalid output"),
    ],
)
def test_mock_intervention_errors_list_supported_phrases(text, message):
    with pytest.raises(ProviderError, match=message):
        asyncio.run(AgentService(MockProvider()).parse(text, CITIZENS))


def test_parsed_interventions_apply_in_the_engine():
    state = initial_world()
    names = {cid: c.name for cid, c in state.citizens.items()}
    command = asyncio.run(AgentService(MockProvider()).parse("Give 1 coin to Finn", names))
    result = Engine(state).intervene(command, "Give 1 coin to Finn")
    assert result.state.citizens["citizen-6"].money == state.citizens["citizen-6"].money + 100
    assert result.events[0].payload.kind == "grant_money"
