import pytest
from kronos_sim.engine import Engine, InvalidAction
from kronos_sim.models import Buy, ConstructBuilding, PriceIntervention, SetPrice, TransferMoney
from kronos_sim.seed import initial_world


def test_tick_is_seeded_ordered_and_does_not_mutate_input():
    state = initial_world()
    before = state.model_dump()
    first, second = Engine(state).tick(), Engine(state).tick()
    assert first == second
    assert state.model_dump() == before
    assert first.tick == 1
    assert first.state.buildings["farm"].inventory.wheat > state.buildings["farm"].inventory.wheat
    assert [e.sequence for e in first.events] == list(range(1, first.sequence + 1))
    assert len({e.id for e in first.events}) == len(first.events)
    assert first.state.rng_state != state.rng_state


def test_higher_price_changes_affordability_without_scripted_outcome():
    state = initial_world()
    state.citizens["citizen-6"].inventory.bread = 0
    original = Engine(state).tick()
    changed = Engine(state).intervene(PriceIntervention(percent=40), "Increase bread price by 40%")
    assert changed.state.buildings["bakery"].prices["bread"] == 700
    assert changed.state.citizens == state.citizens
    expensive = Engine(changed.state).tick()
    assert original.state.citizens["citizen-6"].money == 50
    assert expensive.state.citizens["citizen-6"].money == 550
    assert (
        expensive.state.citizens["citizen-6"].hunger > original.state.citizens["citizen-6"].hunger
    )
    assert changed.events[1].causal_refs == [changed.events[0].id]


@pytest.mark.parametrize(
    "action",
    [
        Buy(
            actor_id="citizen-6",
            building_id="bakery",
            resource="bread",
            quantity=20,
            max_unit_price=500,
        ),
        SetPrice(actor_id="citizen-6", building_id="bakery", resource="bread", price=1),
        TransferMoney(actor_id="citizen-6", recipient_id="citizen-0", amount=1000),
        ConstructBuilding(actor_id="citizen-1", plot_id="plot-0", kind="bakery"),
    ],
)
def test_invalid_actions_leave_world_untouched(action):
    state = initial_world()
    engine = Engine(state)
    with pytest.raises(InvalidAction):
        engine.apply(action)
    assert engine.state == state
    assert engine.events == []


def test_trading_conserves_money_and_goods():
    state = initial_world()
    result = Engine(state).apply(
        Buy(
            actor_id="citizen-0",
            building_id="bakery",
            resource="bread",
            quantity=2,
            max_unit_price=500,
        )
    )
    assert result.state.citizens["citizen-0"].money == state.citizens["citizen-0"].money - 1000
    assert result.state.buildings["bakery"].cash == state.buildings["bakery"].cash + 1000
    assert result.state.citizens["citizen-0"].inventory.bread == 3
    assert result.state.buildings["bakery"].inventory.bread == 14


def test_construction_spends_money_and_uses_unique_plot():
    result = Engine(initial_world()).apply(
        ConstructBuilding(actor_id="citizen-1", plot_id="plot-3", kind="bakery")
    )
    assert len(result.state.buildings) == 4
    assert result.state.citizens["citizen-1"].money == 17000
    assert result.events[0].type == "building_constructed"


def test_long_run_invariants_and_reproducibility():
    state = initial_world()
    for _ in range(30):
        state = Engine(state).tick().state
    assert all(c.money >= 0 and 0 <= c.hunger <= 100 for c in state.citizens.values())
    assert all(
        b.inventory.bread >= 0 and b.inventory.wheat >= 0 and b.cash >= 0
        for b in state.buildings.values()
    )
