"""V1 growth uses the existing entities, commands, and event stream."""

import pytest
from kronos_sim import models as m
from kronos_sim.engine import Engine, InvalidAction
from kronos_sim.seed import initial_world


def quiet_world():
    state = initial_world()
    for citizen in state.citizens.values():
        citizen.money = 0
        citizen.hunger = 60
    return state


def test_full_land_opens_two_persistable_plots_at_deterministic_positions():
    state = quiet_world()
    state.plots["plot-3"].tenant_id = "citizen-5"
    state.plots["plot-4"].tenant_id = "citizen-6"
    left, right = Engine(state).tick(), Engine(state).tick()
    assert left == right
    opened = [e for e in left.events if e.type == "plot_opened"]
    assert len(opened) == 2
    assert [e.payload.position for e in opened] == [m.Position(x=-4, z=9), m.Position(x=0, z=9)]
    assert len({(p.position.x, p.position.z) for p in left.state.plots.values()}) == 8
    for event in opened:
        plot = left.state.plots[event.payload.entity_id]
        assert plot.owner_id is None and plot.tenant_id is None and plot.rent == 0
        assert plot.position == event.payload.position
    assert not any(e.type == "plot_opened" for e in Engine(left.state).tick().events)
    assert len(state.plots) == 6  # Candidate growth never mutates its input.


@pytest.mark.parametrize(
    ("tick", "hunger", "slots", "arrives"),
    [
        (2, 49, True, True),
        (1, 49, True, False),
        (2, 50, True, False),
        (2, 49, False, False),
    ],
)
def test_newcomer_thresholds_and_next_day_application(tick, hunger, slots, arrives):
    state = quiet_world()
    state.tick = tick
    for citizen in state.citizens.values():
        # No bread so daily hunger, not consumption, determines the threshold.
        citizen.inventory.bread = 0
        citizen.hunger = hunger - 20
    if not slots:
        for building in state.buildings.values():
            building.job_slots = sum(c.employer_id == building.id for c in state.citizens.values())
    result = Engine(state).tick()
    new_ids = set(result.state.citizens) - set(state.citizens)
    assert bool(new_ids) is arrives
    if arrives:
        (cid,) = new_ids
        newcomer = result.state.citizens[cid]
        assert newcomer.money == 1000 and newcomer.employer_id is None
        (application,) = result.state.job_applications.values()
        assert application.citizen_id == cid and application.tick == 3
        events = [e for e in result.events if e.type in ("citizen_spawned", "job_applied")]
        assert [e.type for e in events] == ["citizen_spawned", "job_applied"]
        following = Engine(result.state).tick()
        assert following.state.citizens[cid].employer_id == application.building_id
        # Due applications are hired before this day's wage payment.
        assert following.state.citizens[cid].money == 1150
        types = [e.type for e in following.events]
        assert types.index("job_application_resolved") < types.index("transaction_completed")


@pytest.mark.parametrize(("money", "founds"), [(8000, False), (8001, True)])
def test_one_saver_founds_least_common_business_with_capital(money, founds):
    state = quiet_world()
    state.citizens["citizen-0"].money = money
    state.citizens["citizen-0"].employer_id = None
    state.citizens["citizen-1"].money = money
    state.citizens["citizen-1"].employer_id = None
    # Make market the least common type without creating a second construction system.
    state = Engine(state).apply(m.CloseBusiness(actor_id="citizen-2", building_id="market")).state
    state.citizens["citizen-2"].money = 0
    before = sum(c.money for c in state.citizens.values()) + sum(
        b.cash for b in state.buildings.values()
    )
    result = Engine(state).tick()
    founded = [e for e in result.events if e.type == "building_constructed"]
    assert len(founded) == int(founds)
    if founds:
        business = result.state.buildings[founded[0].payload.entity_id]
        assert business.kind == "market" and business.owner_id == "citizen-0"
        assert business.cash == 5000
        assert result.state.citizens["citizen-0"].money == money - 5000
        assert result.state.citizens["citizen-1"].money == money
    after = sum(c.money for c in result.state.citizens.values()) + sum(
        b.cash for b in result.state.buildings.values()
    )
    assert before == after


@pytest.mark.parametrize(
    ("cash", "level", "full", "upgrades"),
    [
        (10300, 1, True, False),
        (10301, 1, True, True),
        (20000, 3, True, False),
        (20000, 1, False, False),
    ],
)
def test_busy_upgrade_spends_business_cash_and_adds_two_slots(cash, level, full, upgrades):
    state = quiet_world()
    farm = state.buildings["farm"]
    farm.cash, farm.level, farm.job_slots = cash, level, 2 if full else 3
    result = Engine(state).tick()
    grown = result.state.buildings["farm"]
    assert grown.level == level + int(upgrades)
    assert grown.job_slots == farm.job_slots + 2 * int(upgrades)
    assert grown.cash == cash - 300 - 2500 * int(upgrades)
    assert bool([e for e in result.events if e.type == "building_upgraded"]) is upgrades


def test_manual_upgrade_shares_capacity_rule_and_rejects_non_owner():
    state = initial_world()
    result = Engine(state).apply(m.UpgradeBuilding(actor_id="citizen-0", building_id="farm"))
    assert result.state.buildings["farm"].level == 2
    assert result.state.buildings["farm"].job_slots == 5
    assert result.state.citizens["citizen-0"].money == 15500
    with pytest.raises(InvalidAction, match="Only the owner"):
        Engine(state).apply(m.UpgradeBuilding(actor_id="citizen-1", building_id="farm"))


@pytest.mark.parametrize(
    ("money", "employed", "rents"),
    [
        (2000, True, False),
        (2001, True, True),
        (2500, False, False),
    ],
)
def test_workers_rent_one_affordable_owned_home(money, employed, rents):
    state = quiet_world()
    for citizen in state.citizens.values():
        citizen.employer_id = None
    worker = state.citizens["citizen-3"]
    worker.money = money
    worker.employer_id = "farm" if employed else None
    for pid in ("plot-3", "plot-4"):
        state.plots[pid].owner_id = "citizen-0"
        state.plots[pid].rent = 300
    # Exercise the threshold after daily wages, not before them.
    engine = Engine(state)
    engine._growth_rules()
    result = engine.result()
    leases = [e for e in result.events if e.type == "lot_leased"]
    assert len(leases) == int(rents)
    assert (result.state.plots["plot-3"].tenant_id == worker.id) is rents
    assert result.state.plots["plot-4"].tenant_id is None
    # Existing lease semantics defer payment to the weekly collection.
    assert result.state.citizens[worker.id].money == money
    second = Engine(result.state)
    second._growth_rules()
    assert not any(e.type == "lot_leased" for e in second.events)


def test_growth_obeys_current_policies_and_empty_world_does_not_crash():
    state = initial_world()
    state.policies.min_wage = 300
    state.policies.bread_price_cap = 400
    engine = Engine(state)
    engine._growth_rules()
    founded = next(e for e in engine.events if e.type == "building_constructed")
    business = engine.state.buildings[founded.payload.entity_id]
    assert business.wage == 300 and business.prices["bread"] == 400
    state.citizens.clear()
    state.buildings.clear()
    state.plots.clear()
    state.job_applications.clear()
    assert Engine(state).tick().events[-1].type == "tick_completed"


def test_growth_is_deterministic_with_conserved_references_for_thirty_days():
    left, right = initial_world(), initial_world()
    for _ in range(30):
        a, b = Engine(left).tick(), Engine(right).tick()
        assert a == b
        left, right = a.state, b.state
        assert len({v.plot_id for v in left.buildings.values()}) == len(left.buildings)
        for business in left.buildings.values():
            assert business.plot_id in left.plots and business.owner_id in left.citizens
            assert (
                sum(c.employer_id == business.id for c in left.citizens.values())
                <= business.job_slots
            )
        for application in left.job_applications.values():
            assert (
                application.building_id in left.buildings
                and application.citizen_id in left.citizens
            )


def test_landlord_cannot_count_another_tenants_home_as_their_own():
    state = quiet_world()
    worker = state.citizens["citizen-3"]
    worker.money = 2500
    state.plots["plot-3"].owner_id = worker.id
    state.plots["plot-3"].tenant_id = "citizen-6"
    state.plots["plot-4"].owner_id = "citizen-0"
    state.plots["plot-4"].rent = 300
    engine = Engine(state)
    engine._growth_rules()
    assert engine.state.plots["plot-4"].tenant_id == worker.id
    assert engine.state.plots["plot-3"].tenant_id == "citizen-6"
