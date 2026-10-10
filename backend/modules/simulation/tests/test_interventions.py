"""Player interventions: each kind is engine-validated and logged with its concrete events."""

import pytest
from kronos_sim.engine import EVENT, Engine, InvalidAction
from kronos_sim.models import (
    GrantIntervention,
    HungerIntervention,
    InterventionResult,
    PolicyIntervention,
    PriceIntervention,
    ResourceIntervention,
    WageIntervention,
)
from kronos_sim.seed import initial_world
from pydantic import ValidationError


def intervene(command, state=None, text="test"):
    return Engine(state or initial_world()).intervene(command, text)


def head(result, kind):
    event = result.events[0]
    assert event.type == "intervention_applied"
    assert event.payload.kind == kind
    assert event.payload.command.type == kind
    assert all(event.id in e.causal_refs for e in result.events[1:])
    return event


def code(command, state=None):
    with pytest.raises(InvalidAction) as error:
        intervene(command, state)
    return error.value.code


def test_price_intervention_keeps_its_payload():
    result = intervene(PriceIntervention(percent=40), text="Increase bread price by 40%")
    event = head(result, "modify_price")
    assert (event.payload.percent, event.payload.scope) == (40, "all_bakeries")
    assert [e.type for e in result.events] == ["intervention_applied", "price_changed"]
    assert result.state.buildings["bakery"].prices["bread"] == 700


def test_old_intervention_events_still_load():
    old = EVENT.validate_python(
        dict(
            id="main:1",
            branch_id="main",
            tick=0,
            sequence=1,
            type="intervention_applied",
            payload=dict(text="Increase bread price by 40%", scope="all_bakeries", percent=40),
        )
    )
    assert (old.payload.kind, old.payload.command) == ("modify_price", None)


def test_set_wages_absolutely_or_by_percent_within_the_minimum_wage():
    result = intervene(WageIntervention(wage=300))
    head(result, "set_wage")
    assert {b.wage for b in result.state.buildings.values()} == {300}
    assert [e.type for e in result.events[1:]] == ["wage_changed"] * 3
    assert result.state.citizens["citizen-3"].memories == [
        "My wage at Goldenfield Farm went from 150 to 300 cents"
    ]
    cut = intervene(WageIntervention(percent=-10), result.state)
    assert {b.wage for b in cut.state.buildings.values()} == {270}
    state = initial_world()
    state.policies.min_wage = 200
    assert code(WageIntervention(wage=100), state) == "bad_params"
    assert code(WageIntervention(wage=150)) == "bad_params"  # Nothing would change.
    with pytest.raises(ValidationError):
        WageIntervention(wage=100, percent=10)


def test_grants_give_to_everyone_and_take_without_going_negative():
    state = initial_world()
    given = intervene(GrantIntervention(amount=500), state)
    event = head(given, "grant_money")
    assert event.payload.affected_ids == sorted(state.citizens)
    for cid, citizen in given.state.citizens.items():
        assert citizen.money == state.citizens[cid].money + 500
    transfers = [e.payload for e in given.events[1:]]
    assert {(t.sender_id, t.amount) for t in transfers} == {("town", 500)}
    assert given.state.citizens["citizen-6"].memories == ["The town gave me 500 cents"]
    taken = intervene(GrantIntervention(citizen_id="citizen-6", amount=-5000), state)
    assert taken.state.citizens["citizen-6"].money == 0
    assert taken.events[1].payload.recipient_id == "town"
    assert taken.events[1].payload.amount == 550
    broke = taken.state
    assert code(GrantIntervention(citizen_id="citizen-6", amount=-1), broke) == (
        "insufficient_funds"
    )
    assert code(GrantIntervention(citizen_id="nobody", amount=1)) == "unknown_entity"


def test_harvest_boom_drought_and_regrowth():
    state = initial_world()
    stock = state.resources["wheat"].stock
    boom = intervene(ResourceIntervention(stock_change=50), state)
    head(boom, "adjust_resource")
    assert boom.state.resources["wheat"].stock == stock + 50
    drought = intervene(ResourceIntervention(stock_change=-10000), state)
    assert drought.state.resources["wheat"].stock == 0
    slow = intervene(ResourceIntervention(regen_per_tick=0), state)
    assert slow.state.resources["wheat"].regen_per_tick == 0
    assert code(ResourceIntervention(regen_per_tick=0), slow.state) == "bad_params"


def test_feast_and_famine_clamp_hunger_and_are_remembered():
    state = initial_world()
    famine = intervene(HungerIntervention(change=90), state)
    head(famine, "adjust_hunger")
    assert {c.hunger for c in famine.state.citizens.values()} == {100}
    assert famine.state.citizens["citizen-0"].memories == ["A famine made me hungrier"]
    feast = intervene(HungerIntervention(citizen_id="citizen-0", change=-30), state)
    assert feast.state.citizens["citizen-0"].hunger == 0
    assert feast.events[0].payload.affected_ids == ["citizen-0"]
    assert code(HungerIntervention(citizen_id="citizen-0", change=-10), feast.state) == (
        "bad_params"
    )


def test_set_policy_applies_now_and_enforces_it():
    result = intervene(PolicyIntervention(kind="min_wage", value=250))
    head(result, "set_policy")
    assert result.state.policies.min_wage == 250
    assert [e.type for e in result.events[1:]] == ["policy_changed"] + ["wage_changed"] * 3
    assert {b.wage for b in result.state.buildings.values()} == {250}
    capped = intervene(PolicyIntervention(kind="bread_price_cap", value=400))
    assert capped.state.buildings["bakery"].prices["bread"] == 400
    tax = intervene(PolicyIntervention(kind="market_tax", value=500))
    assert tax.state.policies.market_tax_bps == 500
    assert code(PolicyIntervention(kind="market_tax", value=0)) == "bad_params"
    with pytest.raises(ValidationError):
        PolicyIntervention(kind="market_tax", value=20000)
    # The price intervention respects a cap already in force.
    assert code(PriceIntervention(percent=10), capped.state) == "bad_params"


def test_intervention_result_accepts_every_kind():
    result = intervene(GrantIntervention(amount=1))
    wire = InterventionResult(command=GrantIntervention(amount=1), update=result)
    assert InterventionResult.model_validate_json(wire.model_dump_json()).command.amount == 1
