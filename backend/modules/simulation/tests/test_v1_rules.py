"""v1 data-model rules: job application status, closing rejects applications, core invariants."""

import pytest
from kronos_sim.engine import Engine, InvalidAction
from kronos_sim.models import (
    ApplyJob,
    CloseBusiness,
    Evict,
    Fire,
    FoundBusiness,
    Hire,
    RejectApplication,
    SetPrice,
    SetWage,
    UpgradeBuilding,
    WorldState,
)
from kronos_sim.queries import job_openings
from kronos_sim.seed import initial_world


def _apply(state, action):
    return Engine(state).apply(action)


def _statuses(state):
    return {a.id: (a.citizen_id, a.building_id, a.status) for a in state.job_applications.values()}


def _resolutions(events):
    return [
        (e.payload.citizen_id, e.payload.building_id, e.payload.outcome, e.actor_id)
        for e in events
        if e.type == "job_application_resolved"
    ]


def test_applications_start_pending_and_keep_their_record_when_resolved():
    state = _apply(initial_world(), ApplyJob(actor_id="citizen-5", building_id="market")).state
    assert state.job_applications["application-main-1"].status == "pending"
    rejected = _apply(
        state, RejectApplication(actor_id="citizen-2", building_id="market", citizen_id="citizen-5")
    ).state
    assert _statuses(rejected) == {"application-main-1": ("citizen-5", "market", "rejected")}
    # A rejected record does not block a fresh application, and only pending ones are open.
    again = _apply(rejected, ApplyJob(actor_id="citizen-5", building_id="market")).state
    assert [a.status for a in again.job_applications.values()] == ["rejected", "pending"]
    with pytest.raises(InvalidAction) as error:
        _apply(again, ApplyJob(actor_id="citizen-5", building_id="market"))
    assert error.value.code == "bad_params"
    hired = _apply(
        again, Hire(actor_id="citizen-2", building_id="market", citizen_id="citizen-5")
    ).state
    assert [a.status for a in hired.job_applications.values()] == ["rejected", "hired"]
    # Resolved records are history: hire/reject no longer find them, ticks leave them alone.
    hired.citizens["citizen-5"].employer_id = None
    with pytest.raises(InvalidAction) as error:
        _apply(hired, Hire(actor_id="citizen-2", building_id="market", citizen_id="citizen-5"))
    assert error.value.code == "bad_params"
    with pytest.raises(InvalidAction) as error:
        _apply(
            hired,
            RejectApplication(actor_id="citizen-2", building_id="market", citizen_id="citizen-5"),
        )
    assert error.value.code == "bad_params"
    ticked = Engine(hired).tick()
    assert _resolutions(ticked.events) == []
    assert _statuses(ticked.state) == _statuses(hired)


def test_job_openings_list_only_pending_applicants():
    state = _apply(initial_world(), ApplyJob(actor_id="citizen-5", building_id="market")).state
    state = _apply(state, ApplyJob(actor_id="citizen-6", building_id="market")).state
    state = _apply(
        state, RejectApplication(actor_id="citizen-2", building_id="market", citizen_id="citizen-5")
    ).state
    market = next(o for o in job_openings(state) if o.building_id == "market")
    assert market.applicant_ids == ["citizen-6"]


def test_saved_applications_without_status_load_as_pending():
    data = _apply(
        initial_world(), ApplyJob(actor_id="citizen-5", building_id="market")
    ).state.model_dump()
    del data["job_applications"]["application-main-1"]["status"]
    state = WorldState.model_validate(data)
    assert state.job_applications["application-main-1"].status == "pending"
    hired = _apply(state, Hire(actor_id="citizen-2", building_id="market", citizen_id="citizen-5"))
    assert hired.state.job_applications["application-main-1"].status == "hired"


def test_closing_a_business_rejects_its_pending_applications():
    state = _apply(initial_world(), ApplyJob(actor_id="citizen-5", building_id="market")).state
    state = _apply(state, ApplyJob(actor_id="citizen-5", building_id="farm")).state
    result = _apply(state, CloseBusiness(actor_id="citizen-2", building_id="market"))
    assert _resolutions(result.events) == [("citizen-5", "market", "rejected", "citizen-2")]
    event = next(e for e in result.events if e.type == "job_application_resolved")
    assert set(event.payload.model_dump()) == {
        "application_id",
        "citizen_id",
        "building_id",
        "outcome",
    }
    assert [e.type for e in result.events][-1] == "building_removed"
    statuses = {a.building_id: a.status for a in result.state.job_applications.values()}
    assert statuses == {"market": "rejected", "farm": "pending"}
    assert result.state.citizens["citizen-5"].memories[-1] == (
        "Market Square rejected my application"
    )


def test_bankruptcy_rejects_pending_applications():
    state = initial_world()
    state.buildings["market"].cash = 0
    for _ in (1, 2):
        state = Engine(state).tick().state
    state = _apply(state, ApplyJob(actor_id="citizen-5", building_id="market")).state
    result = Engine(state).tick()
    assert "market" not in result.state.buildings
    assert ("citizen-5", "market", "rejected", None) in _resolutions(result.events)
    assert result.state.job_applications["application-main-" + str(state.sequence)].status == (
        "rejected"
    )


def test_eviction_rejects_pending_applications_at_the_closed_business():
    from kronos_sim.engine import EVICTION_PERIODS

    state = _apply(
        initial_world(),
        FoundBusiness(actor_id="citizen-5", plot_id="plot-5", kind="bakery", capital=5000),
    ).state
    bid = next(b.id for b in state.buildings.values() if b.plot_id == "plot-5")
    state = _apply(state, ApplyJob(actor_id="citizen-6", building_id=bid)).state
    state.plots["plot-5"].missed_periods = EVICTION_PERIODS
    result = _apply(state, Evict(actor_id="citizen-0", plot_id="plot-5"))
    assert _resolutions(result.events) == [("citizen-6", bid, "rejected", "citizen-0")]
    assert [a.status for a in result.state.job_applications.values()] == ["rejected"]


@pytest.mark.parametrize(
    "action",
    [
        SetPrice(actor_id="citizen-5", building_id="market", resource="bread", price=1),
        SetWage(actor_id="citizen-5", building_id="market", wage=300),
        Hire(actor_id="citizen-5", building_id="market", citizen_id="citizen-6"),
        Fire(actor_id="citizen-5", building_id="market", citizen_id="citizen-3"),
        UpgradeBuilding(actor_id="citizen-5", building_id="market"),
        CloseBusiness(actor_id="citizen-5", building_id="market"),
    ],
)
def test_only_the_owner_manages_a_business(action):
    with pytest.raises(InvalidAction) as error:
        _apply(initial_world(), action)
    assert error.value.code == "not_owner"


def test_one_building_per_plot_and_build_rights():
    from kronos_sim.models import ConstructBuilding

    state = initial_world()
    occupied = next(iter(state.buildings.values())).plot_id
    for action in (
        ConstructBuilding(actor_id="citizen-5", plot_id=occupied, kind="farm"),
        FoundBusiness(actor_id="citizen-5", plot_id=occupied, kind="farm", capital=5000),
    ):
        with pytest.raises(InvalidAction) as error:
            _apply(state, action)
        assert error.value.code == "lot_occupied"
    town = next(
        p.id
        for p in state.plots.values()
        if p.owner_id is None and not any(b.plot_id == p.id for b in state.buildings.values())
    )
    built = _apply(state, ConstructBuilding(actor_id="citizen-5", plot_id=town, kind="farm"))
    assert sum(b.plot_id == town for b in built.state.buildings.values()) == 1
    with pytest.raises(InvalidAction) as error:
        _apply(built.state, ConstructBuilding(actor_id="citizen-6", plot_id=town, kind="farm"))
    assert error.value.code == "lot_occupied"


def test_hiring_stops_at_job_slots():
    state = initial_world()
    market = state.buildings["market"]
    staff = sum(c.employer_id == "market" for c in state.citizens.values())
    market.job_slots = staff + 1
    state = _apply(state, ApplyJob(actor_id="citizen-5", building_id="market")).state
    state = _apply(state, ApplyJob(actor_id="citizen-6", building_id="market")).state
    state = _apply(
        state, Hire(actor_id="citizen-2", building_id="market", citizen_id="citizen-5")
    ).state
    with pytest.raises(InvalidAction) as error:
        _apply(state, Hire(actor_id="citizen-2", building_id="market", citizen_id="citizen-6"))
    assert error.value.code == "no_free_slot"
    with pytest.raises(InvalidAction) as error:
        _apply(state, ApplyJob(actor_id="citizen-0", building_id="market"))
    assert error.value.code in {"no_free_slot", "already_employed"}


@pytest.mark.parametrize(
    "path,value",
    [
        (("citizens", "citizen-5", "money"), -1),
        (("citizens", "citizen-5", "hunger"), -1),
        (("citizens", "citizen-5", "hunger"), 101),
        (("citizens", "citizen-5", "inventory", "bread"), -1),
        (("citizens", "citizen-5", "inventory", "wheat"), -1),
        (("buildings", "market", "cash"), -1),
        (("buildings", "market", "inventory", "bread"), -1),
        (("buildings", "market", "inventory", "wheat"), -1),
    ],
)
def test_committed_states_never_hold_negative_amounts_or_bad_hunger(path, value):
    from pydantic import ValidationError

    data = initial_world().model_dump()
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        WorldState.model_validate(data)
    # The engine revalidates every committed state, so an in-place corruption cannot commit.
    engine = Engine(initial_world())
    holder = getattr(engine.state, path[0])[path[1]]
    for key in path[2:-1]:
        holder = getattr(holder, key)
    setattr(holder, path[-1], value)
    with pytest.raises(ValidationError):
        engine.result()
