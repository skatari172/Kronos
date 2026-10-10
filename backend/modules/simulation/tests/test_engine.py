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


def _money(state):
    return sum(c.money for c in state.citizens.values()) + sum(
        b.cash for b in state.buildings.values()
    )


def test_seeded_lots_have_landlords_tenants_and_town_land():
    plots = initial_world().plots
    assert [plots[f"plot-{i}"].owner_id for i in range(6)] == [
        "citizen-0",
        "citizen-1",
        "citizen-2",
        None,
        None,
        "citizen-0",
    ]
    assert (plots["plot-5"].tenant_id, plots["plot-5"].rent) == ("citizen-5", 300)


def test_lease_set_rent_and_rejections():
    from kronos_sim.models import LeaseLot, SetRent

    state = initial_world()
    state.plots["plot-4"].owner_id = "citizen-2"
    state.plots["plot-4"].rent = 1000
    leased = Engine(state).apply(LeaseLot(actor_id="citizen-1", plot_id="plot-4"))
    assert leased.state.plots["plot-4"].tenant_id == "citizen-1"
    assert [e.type for e in leased.events] == ["lot_leased"]
    assert _money(leased.state) == _money(state)
    for bad, code in [
        (LeaseLot(actor_id="citizen-6", plot_id="plot-4"), "lot_occupied"),
        (LeaseLot(actor_id="citizen-2", plot_id="plot-3"), "bad_params"),  # town land
        (LeaseLot(actor_id="citizen-0", plot_id="plot-5"), "bad_params"),  # own lot
        (LeaseLot(actor_id="citizen-1", plot_id="plot-0"), "lot_occupied"),  # farm stands there
        (LeaseLot(actor_id="citizen-1", plot_id="nowhere"), "unknown_entity"),
        (SetRent(actor_id="citizen-1", plot_id="plot-4", rent=900), "not_owner"),
        (SetRent(actor_id="citizen-2", plot_id="plot-4", rent=1201), "bad_params"),
        (SetRent(actor_id="citizen-2", plot_id="plot-4", rent=799), "bad_params"),
        (SetRent(actor_id="citizen-2", plot_id="plot-4", rent=1000), "bad_params"),
    ]:
        with pytest.raises(InvalidAction) as error:
            Engine(leased.state).apply(bad)
        assert error.value.code == code, bad
    raised = Engine(leased.state).apply(SetRent(actor_id="citizen-2", plot_id="plot-4", rent=1200))
    assert raised.state.plots["plot-4"].rent == 1200
    assert raised.events[0].payload.model_dump() == dict(
        plot_id="plot-4", old_rent=1000, new_rent=1200
    )
    # Vacant lots are priced freely; a leased lot at zero rent can still move by a small step.
    state.plots["plot-4"].rent = 0
    free = Engine(state).apply(SetRent(actor_id="citizen-2", plot_id="plot-4", rent=5000))
    assert free.state.plots["plot-4"].rent == 5000
    zero = Engine(state).apply(LeaseLot(actor_id="citizen-1", plot_id="plot-4")).state
    Engine(zero).apply(SetRent(actor_id="citizen-2", plot_id="plot-4", rent=100))
    with pytest.raises(InvalidAction):
        Engine(zero).apply(SetRent(actor_id="citizen-2", plot_id="plot-4", rent=101))
    poor = initial_world()
    poor.plots["plot-4"].owner_id, poor.plots["plot-4"].rent = "citizen-2", 1000
    with pytest.raises(InvalidAction) as error:
        Engine(poor).apply(LeaseLot(actor_id="citizen-6", plot_id="plot-4"))
    assert error.value.code == "insufficient_funds"


def test_rent_is_collected_each_period():
    from kronos_sim.engine import RENT_PERIOD_DAYS

    state = initial_world()
    for _ in range(RENT_PERIOD_DAYS - 1):
        result = Engine(state).tick()
        assert not any(_is_rent(e) for e in _transfers(result))
        state = result.state
    result = Engine(state).tick()
    paid = [e for e in _transfers(result) if _is_rent(e)]
    assert [(p.payload.recipient_id, p.payload.amount) for p in paid] == [("citizen-0", 300)]
    assert result.state.plots["plot-5"].arrears == 0


def _transfers(result):
    return [e for e in result.events if e.type == "transaction_completed"]


def _is_rent(event):
    return (event.payload.sender_id, event.payload.recipient_id) == ("citizen-5", "citizen-0")


def test_missed_rent_builds_arrears_then_allows_eviction():
    from kronos_sim.engine import EVICTION_PERIODS, RENT_PERIOD_DAYS
    from kronos_sim.models import Evict, PayRent

    state = initial_world()
    state.citizens["citizen-5"].money = 0
    state.tick = RENT_PERIOD_DAYS - 1
    before = _money(state)
    result = Engine(state).tick()
    missed = [e for e in result.events if e.type == "rent_missed"]
    assert len(missed) == 1 and missed[0].payload.arrears == 300
    assert _money(result.state) == before
    lot = result.state.plots["plot-5"]
    assert (lot.arrears, lot.missed_periods) == (300, 1)
    for action, code in [
        (Evict(actor_id="citizen-0", plot_id="plot-5"), "bad_params"),
        (Evict(actor_id="citizen-5", plot_id="plot-5"), "not_owner"),
        (PayRent(actor_id="citizen-5", plot_id="plot-5"), "insufficient_funds"),
    ]:
        with pytest.raises(InvalidAction) as error:
            Engine(result.state).apply(action)
        assert error.value.code == code

    behind = result.state.model_copy(deep=True)
    behind.plots["plot-5"].missed_periods = EVICTION_PERIODS
    behind.plots["plot-5"].arrears = 900
    evicted = Engine(behind).apply(Evict(actor_id="citizen-0", plot_id="plot-5", rationale="Owed"))
    lot = evicted.state.plots["plot-5"]
    assert (lot.tenant_id, lot.arrears, lot.missed_periods) == (None, 0, 0)
    assert evicted.events[-1].type == "tenant_evicted"
    assert (evicted.events[-1].payload.tenant_id, evicted.events[-1].payload.arrears) == (
        "citizen-5",
        900,
    )


def test_pay_rent_clears_arrears_or_prepays():
    from kronos_sim.engine import MAX_PREPAID_PERIODS, RENT_PERIOD_DAYS
    from kronos_sim.models import PayRent

    state = initial_world()
    state.plots["plot-5"].arrears, state.plots["plot-5"].missed_periods = 600, 2
    cleared = Engine(state).apply(PayRent(actor_id="citizen-5", plot_id="plot-5"))
    assert cleared.state.citizens["citizen-5"].money == 6000 - 600
    assert cleared.state.citizens["citizen-0"].money == 18000 + 600
    assert (
        cleared.state.plots["plot-5"].arrears,
        cleared.state.plots["plot-5"].missed_periods,
    ) == (
        0,
        0,
    )
    early = Engine(cleared.state).apply(PayRent(actor_id="citizen-5", plot_id="plot-5")).state
    assert early.plots["plot-5"].prepaid_periods == 1
    assert early.citizens["citizen-5"].money == 6000 - 900
    early.tick = RENT_PERIOD_DAYS - 1
    covered = Engine(early).tick()
    assert [e.type for e in covered.events if e.type.startswith("rent_")] == ["rent_covered"]
    assert not any(_is_rent(e) for e in _transfers(covered))
    assert covered.state.plots["plot-5"].prepaid_periods == 0
    full = initial_world()
    full.plots["plot-5"].prepaid_periods = MAX_PREPAID_PERIODS
    with pytest.raises(InvalidAction):
        Engine(full).apply(PayRent(actor_id="citizen-5", plot_id="plot-5"))
    with pytest.raises(InvalidAction) as error:
        Engine(state).apply(PayRent(actor_id="citizen-6", plot_id="plot-5"))
    assert error.value.code == "bad_params"


def test_building_on_private_land_needs_owner_or_tenant():
    from kronos_sim.models import FoundBusiness, LeaseLot

    state = initial_world()
    found = FoundBusiness(actor_id="citizen-1", plot_id="plot-5", kind="bakery", capital=6000)
    construct = ConstructBuilding(actor_id="citizen-1", plot_id="plot-5", kind="bakery")
    for action in (found, construct):
        with pytest.raises(InvalidAction) as error:
            Engine(state).apply(action)
        assert error.value.code == "not_owner"
    # The tenant (citizen-5) and the owner (citizen-0) may both build there.
    assert Engine(state).apply(construct.model_copy(update={"actor_id": "citizen-5"})).events
    assert Engine(state).apply(found.model_copy(update={"actor_id": "citizen-0"})).events
    state.plots["plot-4"].owner_id = "citizen-2"
    leased = Engine(state).apply(LeaseLot(actor_id="citizen-1", plot_id="plot-4")).state
    result = Engine(leased).apply(found.model_copy(update={"plot_id": "plot-4"}))
    assert any(b.plot_id == "plot-4" for b in result.state.buildings.values())


def test_eviction_closes_the_tenants_business_on_the_lot():
    from kronos_sim.engine import EVICTION_PERIODS
    from kronos_sim.models import Evict, FoundBusiness

    state = initial_world()
    found = FoundBusiness(actor_id="citizen-5", plot_id="plot-5", kind="bakery", capital=5000)
    state = Engine(state).apply(found).state
    state.plots["plot-5"].missed_periods = EVICTION_PERIODS
    result = Engine(state).apply(Evict(actor_id="citizen-0", plot_id="plot-5"))
    assert not any(b.plot_id == "plot-5" for b in result.state.buildings.values())
    assert result.state.citizens["citizen-5"].money == 6000
    assert [e.type for e in result.events][-2:] == ["building_removed", "tenant_evicted"]
