"""Growth rules beyond the core v1 set (departures, business cash cap), plus growth over
long runs. Land, newcomers, founding, upgrades and homes are covered in test_growth.py."""

from collections import Counter

from kronos_sim import engine as e
from kronos_sim.engine import Engine
from kronos_sim.models import Loan, Trade, TradeBundle
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
    # Without agents nobody buys bread (it is an agent decision), so which growth events
    # fire depends on the economy; this run only proves the rules keep the world valid.
