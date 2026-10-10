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
"""Daily growth rules in Engine.tick: land, newcomers, leaving, founding, upgrades, homes,
and the business cash cap. Each rule is tested on its own step, then over long runs."""

from collections import Counter

from kronos_sim import engine as e
from kronos_sim.engine import Engine
from kronos_sim.models import Loan, Plot, Position, Trade, TradeBundle
from kronos_sim.seed import initial_world


def step(state, rule: str):
    tx = Engine(state)
    getattr(tx, rule)()
    return tx.result()


def types(result) -> list[str]:
    return [event.type for event in result.events]


def total_money(state) -> int:
    return sum(c.money for c in state.citizens.values()) + sum(
        b.cash for b in state.buildings.values()
    )


def test_land_opens_on_the_outer_ring_once_every_lot_is_used():
    state = initial_world()
    assert step(state, "_open_land").events == []  # plot-3 and plot-4 are free town land.
    state.plots["plot-3"].owner_id = state.plots["plot-4"].owner_id = "citizen-0"
    state.plots["plot-3"].tenant_id = state.plots["plot-4"].tenant_id = "citizen-6"
    first = step(state, "_open_land")
    assert types(first) == ["plot_opened", "plot_opened"]
    opened = [first.state.plots[f"plot-{i}"] for i in (6, 7)]
    assert [(p.position.x, p.position.z) for p in opened] == [(-8, -3), (-8, 3)]
    assert all(p.owner_id is None and p.tenant_id is None for p in opened)
    assert first.events[0].payload.plot_id == "plot-6"
    assert first.events[0].payload.position.x == -8
    assert step(first.state, "_open_land").events == []  # The new lots are free.

    state = first.state
    for plot_id in ("plot-6", "plot-7"):
        state.plots[plot_id].owner_id, state.plots[plot_id].tenant_id = "citizen-0", "citizen-6"
    second = step(state, "_open_land")
    positions = {(p.position.x, p.position.z) for p in second.state.plots.values()}
    assert len(positions) == len(second.state.plots) == 10
    assert (second.state.plots["plot-8"].position.x, second.state.plots["plot-9"].position.x) == (
        8,
        8,
    )


def test_land_skips_taken_positions_and_ids():
    state = initial_world()
    for plot in state.plots.values():
        plot.owner_id, plot.tenant_id = plot.owner_id or "citizen-0", "citizen-6"
    state.plots["plot-9"] = Plot(
        id="plot-9", position=Position(x=-8, z=-3), owner_id="citizen-0", tenant_id="citizen-6"
    )
    result = step(state, "_open_land")
    new = {p.id: (p.position.x, p.position.z) for p in result.state.plots.values()}
    assert new["plot-10"] == (-8, 3) and new["plot-11"] == (8, -3)


def test_newcomer_arrives_every_third_day_and_applies_for_the_biggest_opening():
    state = initial_world()
    state.tick = 3
    result = step(state, "_welcome_newcomer")
    assert types(result) == ["citizen_spawned", "job_applied"]
    newcomer = result.state.citizens["citizen-7"]
    assert newcomer.money == e.NEWCOMER_MONEY
    assert newcomer.name == e.NEWCOMER_NAMES[7 % len(e.NEWCOMER_NAMES)]
    # Market has 2 free slots (farm and bakery have 1 each).
    application = next(iter(result.state.job_applications.values()))
    assert (application.citizen_id, application.building_id, application.status) == (
        "citizen-7",
        "market",
        "pending",
    )
    assert result.events[1].actor_id == "citizen-7"

    state.tick = 4
    assert step(state, "_welcome_newcomer").events == []
    state.tick = 3
    hungry = state.model_copy(deep=True)
    for citizen in hungry.citizens.values():
        citizen.hunger = e.NEWCOMER_MAX_AVG_HUNGER
    assert step(hungry, "_welcome_newcomer").events == []
    full = state.model_copy(deep=True)
    for building in full.buildings.values():
        building.job_slots = sum(1 for c in full.citizens.values() if c.employer_id == building.id)
    assert step(full, "_welcome_newcomer").events == []


def test_newcomer_is_hired_by_the_next_day():
    state = initial_world()
    state.tick = 2
    result = Engine(state).tick()
    assert "citizen_spawned" in types(result)
    after = Engine(result.state).tick().state
    assert after.citizens["citizen-7"].employer_id == "market"


def test_destitute_citizen_leaves_after_three_days_and_leaves_nothing_dangling():
    state = initial_world()
    finn = state.citizens["citizen-6"]
    finn.hunger, finn.money, finn.employer_id = 100, 0, "market"
    plot = state.plots["plot-3"]
    plot.owner_id, plot.tenant_id, plot.rent, plot.arrears = "citizen-2", finn.id, 300, 300
    # A pending trade offer to Finn and a loan offer from him.
    state = (
        Engine(state)
        .apply(
            Trade(
                actor_id="citizen-1",
                recipient_id=finn.id,
                give=TradeBundle(money=100),
                get=TradeBundle(money=0, goods={"bread": 1}),
            )
        )
        .state
    )
    state.loans["loan-x"] = Loan(
        id="loan-x",
        lender_id="citizen-6",
        borrower_id="citizen-5",
        principal=100,
        rate_bps=0,
        due_tick=9,
        amount_owed=100,
    )
    elena = state.citizens["citizen-0"]  # Owns the farm and lots: never leaves.
    elena.hunger, elena.money = 100, 0

    for day in (1, 2):
        state = step(state, "_let_destitute_leave").state
        assert state.citizens["citizen-6"].destitute_days == day
    result = step(state, "_let_destitute_leave")
    s = result.state
    assert "citizen-6" not in s.citizens
    assert s.citizens["citizen-0"].destitute_days == 3
    assert types(result) == [
        "employment_changed",
        "tenant_evicted",
        "loan_expired",
        "trade_expired",
        "citizen_removed",
    ]
    assert result.events[-1].payload.entity_id == "citizen-6"
    assert (s.plots["plot-3"].tenant_id, s.plots["plot-3"].arrears) == (None, 0)
    assert s.loans["loan-x"].status == "expired" and s.trade_offers == {}


def test_destitute_streak_resets_and_pending_applications_are_rejected():
    state = initial_world()
    finn = state.citizens["citizen-6"]
    finn.hunger, finn.money = 100, 0
    state = step(state, "_let_destitute_leave").state
    state.citizens["citizen-6"].hunger = 80
    state = step(state, "_let_destitute_leave").state
    assert state.citizens["citizen-6"].destitute_days == 0

    state.citizens["citizen-6"].hunger = 100
    state.citizens["citizen-6"].destitute_days = 2
    from kronos_sim.models import ApplyJob

    state = Engine(state).apply(ApplyJob(actor_id="citizen-6", building_id="market")).state
    result = step(state, "_let_destitute_leave")
    (application,) = result.state.job_applications.values()
    assert application.status == "rejected"
    assert "job_application_resolved" in types(result)


def test_saver_founds_the_scarcest_kind_on_free_town_land():
    state = initial_world()
    for cid in ("citizen-5", "citizen-6"):
        state.citizens[cid].money = e.FOUNDER_MIN_MONEY + 1
    state.citizens["citizen-0"].money = 10**6  # Already owns a building.
    result = step(state, "_found_by_saver")
    assert types(result) == ["building_constructed", "transaction_completed"]
    (new,) = [b for b in result.state.buildings.values() if b.id not in state.buildings]
    assert (new.owner_id, new.kind, new.plot_id, new.cash) == (
        "citizen-5",
        "farm",  # One of each kind: farm wins the tie.
        "plot-3",
        e.FOUNDER_CAPITAL,
    )
    assert result.state.citizens["citizen-5"].money == e.FOUNDER_MIN_MONEY + 1 - e.FOUNDER_CAPITAL
    assert result.state.citizens["citizen-6"].money == e.FOUNDER_MIN_MONEY + 1  # One a day.

    del state.buildings["market"]
    state.citizens["citizen-2"].money = 0  # Ada no longer owns a building.
    assert step(state, "_found_by_saver").state.buildings[new.id].kind == "market"
    state.citizens["citizen-5"].money = state.citizens["citizen-6"].money = e.FOUNDER_MIN_MONEY
    assert step(state, "_found_by_saver").events == []


def test_saver_needs_unowned_unbuilt_land():
    state = initial_world()
    state.citizens["citizen-6"].money = e.FOUNDER_MIN_MONEY + 1
    state.plots["plot-3"].owner_id = "citizen-0"
    state.plots["plot-4"].tenant_id = "citizen-5"
    assert step(state, "_found_by_saver").events == []


def test_full_rich_business_upgrades_with_more_slots():
    state = initial_world()
    farm = state.buildings["farm"]  # Two employees.
    farm.job_slots, farm.cash = 2, e.UPGRADE_MIN_CASH + 1
    result = step(state, "_upgrade_busy_businesses")
    upgraded = result.state.buildings["farm"]
    assert (upgraded.level, upgraded.job_slots, upgraded.cash) == (
        2,
        2 + e.UPGRADE_JOB_SLOTS,
        e.UPGRADE_MIN_CASH + 1 - e.UPGRADE_COST,
    )
    assert types(result) == ["building_upgraded"]
    assert result.events[0].payload.level == 2 and result.events[0].actor_id == "citizen-0"

    farm.cash = e.UPGRADE_MIN_CASH
    assert step(state, "_upgrade_busy_businesses").events == []
    farm.cash, farm.level = e.UPGRADE_MIN_CASH + 1, e.MAX_LEVEL
    assert step(state, "_upgrade_busy_businesses").events == []
    farm.level, farm.job_slots = 1, 3
    assert step(state, "_upgrade_busy_businesses").events == []  # A slot is free.


def test_employed_saver_rents_a_free_owned_lot():
    state = initial_world()
    del state.buildings["market"]  # plot-2 (Ada's) is now free and owned.
    state.citizens["citizen-2"].employer_id = None
    state.plots["plot-2"].rent = 300
    for cid in ("citizen-0", "citizen-1", "citizen-3"):  # Other employees can't afford it.
        state.citizens[cid].money = 0
    state.citizens["citizen-4"].money = e.RENTER_MIN_MONEY + 1  # Theo works at the bakery.
    state.citizens["citizen-6"].money = 10**5  # Finn has no job.
    state.citizens["citizen-5"].money = 10**5  # Mira already rents plot-5.
    state.citizens["citizen-5"].employer_id = "farm"
    result = step(state, "_rent_homes")
    assert types(result) == ["lot_leased"]
    assert result.state.plots["plot-2"].tenant_id == "citizen-4"
    assert result.events[0].actor_id == "citizen-4"

    state.citizens["citizen-4"].money = e.RENTER_MIN_MONEY
    assert step(state, "_rent_homes").events == []
    state.citizens["citizen-4"].money = e.RENTER_MIN_MONEY + 1
    state.plots["plot-2"].owner_id = "citizen-4"  # Not their own lot.
    assert step(state, "_rent_homes").events == []


def test_business_cash_above_the_cap_is_paid_to_staff():
    state = initial_world()
    bakery = state.buildings["bakery"]  # Staff: citizen-1 (owner) and citizen-4.
    bakery.cash = e.BUSINESS_CASH_CAP + 1001
    farm = state.buildings["farm"]
    farm.cash = e.BUSINESS_CASH_CAP + 70
    for citizen in state.citizens.values():
        if citizen.employer_id == "farm":
            citizen.employer_id = None
    before = total_money(state)
    result = step(state, "_pay_out_surplus")
    s = result.state
    assert total_money(s) == before
    assert s.buildings["bakery"].cash == s.buildings["farm"].cash == e.BUSINESS_CASH_CAP
    assert s.citizens["citizen-1"].money - state.citizens["citizen-1"].money == 501
    assert s.citizens["citizen-4"].money - state.citizens["citizen-4"].money == 500
    assert s.citizens["citizen-0"].money - state.citizens["citizen-0"].money == 70  # No staff.
    paid = [
        (ev.payload.sender_id, ev.payload.recipient_id, ev.payload.amount) for ev in result.events
    ]
    assert paid == [
        ("bakery", "citizen-1", 501),
        ("bakery", "citizen-4", 500),
        ("farm", "citizen-0", 70),
    ]
    assert step(s, "_pay_out_surplus").events == []


def test_growth_runs_inside_tick():
    state = initial_world()
    for plot_id in ("plot-3", "plot-4"):
        state.plots[plot_id].owner_id, state.plots[plot_id].tenant_id = "citizen-0", "citizen-6"
    result = Engine(state).tick()
    assert types(result).count("plot_opened") == e.NEW_PLOTS_PER_EXPANSION
    assert len(result.state.plots) == 8


def test_growth_is_deterministic_for_a_seed():
    def run(seed):
        state = initial_world(seed=seed)
        for _ in range(60):
            state = Engine(state).tick().state
        return state

    assert run(7) == run(7)


def test_120_day_soak_keeps_the_world_valid_and_money_moving():
    state = initial_world()
    start = total_money(state)
    seen = Counter()
    for _ in range(120):
        result = Engine(state).tick()
        state = result.state
        seen.update(types(result))
        citizens, buildings, plots = state.citizens, state.buildings, state.plots
        assert all(c.money >= 0 and 0 <= c.hunger <= 100 for c in citizens.values())
        assert all(b.cash >= 0 and b.cash <= e.BUSINESS_CASH_CAP for b in buildings.values())
        assert len({b.plot_id for b in buildings.values()}) == len(buildings)
        assert all(b.plot_id in plots and b.owner_id in citizens for b in buildings.values())
        assert len({(p.position.x, p.position.z) for p in plots.values()}) == len(plots)
        assert all(p.tenant_id is None or p.tenant_id in citizens for p in plots.values())
        assert all(c.employer_id is None or c.employer_id in buildings for c in citizens.values())
        assert all(
            a.citizen_id in citizens and a.building_id in buildings
            for a in state.job_applications.values()
            if a.status == "pending"
        )
    # Money only enters with newcomers and only leaves through upgrades.
    assert total_money(state) == (
        start
        + seen["citizen_spawned"] * e.NEWCOMER_MONEY
        - seen["building_upgraded"] * e.UPGRADE_COST
    )
    for kind in ("plot_opened", "citizen_spawned", "building_constructed", "building_upgraded"):
        assert seen[kind] > 0, kind
    citizen_money = sum(c.money for c in state.citizens.values())
    assert citizen_money * 2 > total_money(state)  # Most money is held by people, not shops.
