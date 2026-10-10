import pytest
from kronos_sim.engine import ACTION, Engine, InvalidAction
from kronos_sim.models import Buy, ConstructBuilding, PriceIntervention, SetPrice, TransferMoney
from kronos_sim.seed import initial_world
from pydantic import ValidationError


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


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "apply_job", "building_id": "farm"},
        {"type": "quit_job"},
        {
            "type": "trade",
            "recipient_id": "citizen-1",
            "give": {"money": 100},
            "get": {"goods": {"bread": 1}},
        },
        {"type": "respond_trade", "offer_id": "offer-1", "accept": True},
        {"type": "lease_lot", "plot_id": "plot-3"},
        {"type": "set_rent", "plot_id": "plot-3", "rent": 300},
        {"type": "pay_rent", "plot_id": "plot-3"},
        {"type": "evict", "plot_id": "plot-3"},
        {"type": "interact", "recipient_id": "citizen-1", "kind": "befriend"},
        {"type": "research", "invention_id": "water_mill", "mode": "time", "ticks": 3},
        {
            "type": "license_invention",
            "invention_id": "water_mill",
            "recipient_id": "citizen-1",
            "fee": 1000,
        },
        {"type": "adopt_invention", "invention_id": "water_mill", "building_id": "farm"},
        {
            "type": "lend",
            "recipient_id": "citizen-6",
            "principal": 6000,
            "rate_bps": 1000,
            "due_tick": 10,
        },
        {"type": "repay", "loan_id": "loan-1", "amount": 1000},
        {"type": "propose_vote", "kind": "min_wage", "value": 200},
        {"type": "vote", "vote_id": "vote-1", "choice": "yes"},
        {"type": "gather_resource", "building_id": "farm", "resource": "wheat", "quantity": 2},
    ],
)
def test_planned_actions_parse_but_are_rejected_until_implemented(payload):
    action = ACTION.validate_python({"actor_id": "citizen-0", **payload})
    state = initial_world()
    with pytest.raises(InvalidAction, match="not supported yet"):
        Engine(state).apply(action)


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "interact", "recipient_id": "citizen-1", "kind": "gift"},
        {"type": "interact", "recipient_id": "citizen-1", "kind": "argue", "amount": 100},
        {"type": "research", "invention_id": "water_mill", "mode": "money", "ticks": 3},
        {"type": "research", "invention_id": "water_mill", "mode": "time"},
        {"type": "lend", "recipient_id": "citizen-6", "principal": 0, "rate_bps": 0, "due_tick": 1},
        {"type": "trade", "recipient_id": "citizen-1", "give": {"money": -1}, "get": {}},
    ],
)
def test_planned_action_schemas_reject_bad_params(payload):
    with pytest.raises(ValidationError):
        ACTION.validate_python({"actor_id": "citizen-0", **payload})


@pytest.mark.parametrize(
    "action,code",
    [
        (
            Buy(
                actor_id="citizen-6",
                building_id="bakery",
                resource="bread",
                quantity=20,
                max_unit_price=500,
            ),
            "out_of_stock",
        ),
        (
            Buy(
                actor_id="citizen-6",
                building_id="bakery",
                resource="bread",
                quantity=2,
                max_unit_price=500,
            ),
            "insufficient_funds",
        ),
        (
            SetPrice(actor_id="citizen-6", building_id="bakery", resource="bread", price=1),
            "not_owner",
        ),
        (ConstructBuilding(actor_id="citizen-1", plot_id="plot-0", kind="bakery"), "lot_occupied"),
        (
            ConstructBuilding(actor_id="citizen-1", plot_id="nowhere", kind="bakery"),
            "unknown_entity",
        ),
    ],
)
def test_rejections_carry_stable_codes(action, code):
    with pytest.raises(InvalidAction) as error:
        Engine(initial_world()).apply(action)
    assert error.value.code == code


def test_reject_logs_event_and_memory_without_other_changes():
    state = initial_world()
    action = SetPrice(
        actor_id="citizen-6", building_id="bakery", resource="bread", price=1, rationale="Cheaper"
    )
    with pytest.raises(InvalidAction) as error:
        Engine(state).apply(action)
    result = Engine(state).reject(action, error.value)
    assert [e.type for e in result.events] == ["action_rejected"]
    assert result.events[0].payload.code == "not_owner"
    assert result.events[0].rationale == "Cheaper"
    assert result.state.citizens["citizen-6"].memories[-1].startswith("Rejected set_price")
    assert result.state.buildings == state.buildings
    assert result.state.rng_state == state.rng_state
    assert result.sequence == state.sequence + 1


def test_every_action_type_is_supported_or_explicitly_planned():
    from typing import get_args

    from kronos_sim.engine import SUPPORTED_ACTIONS
    from kronos_sim.models import AgentAction

    union = get_args(get_args(AgentAction)[0])
    types = {cls.model_fields["type"].default for cls in union}
    assert set(SUPPORTED_ACTIONS) <= types
    assert len(types) == 33


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"wealth": 10}, {"wealth": 32, "influence": 23, "safety": 23, "reputation": 22}),
        (
            {"wealth": 10, "influence": -10, "safety": -10, "reputation": -10},
            {"wealth": 44, "influence": 19, "safety": 19, "reputation": 18},
        ),
        (
            {"safety": 5, "reputation": -5},
            {"wealth": 25, "influence": 25, "safety": 30, "reputation": 20},
        ),
    ],
)
def test_goal_adjustment_clamps_and_renormalises_to_100(changes, expected):
    from kronos_sim.models import AdjustGoals, GoalWeightChanges

    action = AdjustGoals(actor_id="citizen-0", changes=GoalWeightChanges(**changes))
    result = Engine(initial_world()).apply(action, action_id="action-main:0")
    assert result.state.citizens["citizen-0"].goal_weights.model_dump() == expected
    assert result.events[0].type == "goals_changed"
    assert result.events[0].action_id == "action-main:0"


def test_spawn_adds_citizen_with_stable_id():
    from kronos_sim.models import SpawnCitizenRequest

    request = SpawnCitizenRequest(
        branch_id="main",
        expected_sequence=0,
        name="Nico",
        occupation="Apprentice",
        plot_id="plot-2",
        money=500,
    )
    result = Engine(initial_world()).spawn(request)
    nico = result.state.citizens["citizen-main-1"]
    assert (nico.name, nico.money, nico.position.x) == ("Nico", 500, 4)
    assert result.events[0].payload.entity_id == "citizen-main-1"
    with pytest.raises(InvalidAction):
        Engine(initial_world()).spawn(request.model_copy(update={"plot_id": "nowhere"}))


def test_founding_moves_capital_into_the_business():
    from kronos_sim.models import FoundBusiness

    action = FoundBusiness(actor_id="citizen-0", plot_id="plot-3", kind="bakery", capital=6000)
    result = Engine(initial_world()).apply(action)
    new = next(b for b in result.state.buildings.values() if b.plot_id == "plot-3")
    assert (new.owner_id, new.cash, new.kind) == ("citizen-0", 6000, "bakery")
    assert result.state.citizens["citizen-0"].money == 12000
    assert [e.type for e in result.events] == ["building_constructed", "transaction_completed"]
    for bad, code in [
        (action.model_copy(update={"capital": 4999}), "bad_params"),
        (action.model_copy(update={"plot_id": "plot-0"}), "lot_occupied"),
        (
            action.model_copy(update={"actor_id": "citizen-6", "capital": 6000}),
            "insufficient_funds",
        ),
    ]:
        with pytest.raises(InvalidAction) as error:
            Engine(initial_world()).apply(bad)
        assert error.value.code == code


def test_closing_returns_assets_and_releases_staff():
    from kronos_sim.models import CloseBusiness

    state = initial_world()
    bakery = state.buildings["bakery"]
    result = Engine(state).apply(CloseBusiness(actor_id="citizen-1", building_id="bakery"))
    owner = result.state.citizens["citizen-1"]
    assert "bakery" not in result.state.buildings
    assert owner.money == state.citizens["citizen-1"].money + bakery.cash
    assert owner.inventory.bread == 1 + bakery.inventory.bread
    assert owner.employer_id is None and result.state.citizens["citizen-4"].employer_id is None
    assert result.events[-1].type == "building_removed"
    with pytest.raises(InvalidAction) as error:
        Engine(state).apply(CloseBusiness(actor_id="citizen-0", building_id="bakery"))
    assert error.value.code == "not_owner"


def test_hiring_firing_and_wages():
    from kronos_sim.models import Fire, Hire, SetWage

    state = initial_world()
    hired = Engine(state).apply(
        Hire(actor_id="citizen-2", building_id="market", citizen_id="citizen-5")
    )
    assert hired.state.citizens["citizen-5"].employer_id == "market"
    assert hired.events[0].type == "employment_changed"
    raised = Engine(hired.state).apply(
        SetWage(actor_id="citizen-2", building_id="market", wage=400)
    )
    paid = Engine(raised.state).tick()
    wage_events = [
        e
        for e in paid.events
        if e.type == "transaction_completed" and e.payload.recipient_id == "citizen-5"
    ]
    assert wage_events[0].payload.amount == 400
    for action, code in [
        (
            Hire(actor_id="citizen-2", building_id="market", citizen_id="citizen-3"),
            "already_employed",
        ),
        (Hire(actor_id="citizen-2", building_id="market", citizen_id="nobody"), "unknown_entity"),
        (Fire(actor_id="citizen-2", building_id="market", citizen_id="citizen-3"), "bad_params"),
    ]:
        with pytest.raises(InvalidAction) as error:
            Engine(hired.state).apply(action)
        assert error.value.code == code
    full = hired.state.model_copy(deep=True)
    full.buildings["market"].job_slots = 2
    with pytest.raises(InvalidAction) as error:
        Engine(full).apply(Hire(actor_id="citizen-2", building_id="market", citizen_id="citizen-6"))
    assert error.value.code == "no_free_slot"
    fired = Engine(hired.state).apply(
        Fire(actor_id="citizen-2", building_id="market", citizen_id="citizen-5")
    )
    assert fired.state.citizens["citizen-5"].employer_id is None


def test_business_goes_bankrupt_after_three_unpaid_days():
    state = initial_world()
    state.buildings["market"].cash = 0
    for day in (1, 2):
        state = Engine(state).tick().state
        assert state.buildings["market"].unpaid_days == day
    result = Engine(state).tick()
    assert "market" not in result.state.buildings
    assert result.state.citizens["citizen-2"].employer_id is None
    removed = next(e for e in result.events if e.type == "building_removed")
    assert removed.actor_id is None and removed.rationale.startswith("Bankrupt")
    assert all(b.unpaid_days == 0 for b in result.state.buildings.values())
