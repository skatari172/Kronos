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
