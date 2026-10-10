"""Shared historical queries and branch tools."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from kronos_history import branching
from kronos_sim import models as m

from kronos.dependencies import ServiceDependency

router = APIRouter(prefix="/api", tags=["History"])


@router.get(
    "/history/events", response_model=list[m.SimulationEvent], summary="Read the event ledger"
)
async def events(
    service: ServiceDependency,
    branch_id: str,
    through: int | None = None,
    limit: int = Query(100, ge=1, le=500),
):
    return service.store.list_events(branch_id, through, limit)


@router.get("/events", response_model=list[m.SimulationEvent], summary="Read new village events")
async def events_after(
    service: ServiceDependency,
    after: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    """Read committed events, oldest first, without a realtime connection.

    The cursor is exclusive and scoped to the active branch. Pass the last returned
    sequence as `after`; an empty list means the reader has caught up.
    """
    return service.store.list_events_after(service.state.branch_id, after, limit)

    type: list[str] | None = Query(None, description="Event types (repeat to allow several)"),
    actor: str | None = Query(None, description="Acting citizen ID"),
    target: str | None = Query(None, description="Citizen or entity named in the payload"),
    tick_from: int | None = Query(None, ge=0),
    tick_to: int | None = Query(None, ge=0),
    branch_id: str | None = Query(None, description="Defaults to the active branch"),
):
    """Events with sequence greater than `after`, oldest first, matching every filter.
    Page by passing the last returned sequence as `after`."""
    branch_id = branch_id or service.state.branch_id
    if branch_id != service.state.branch_id:
        service.store.branch(branch_id)  # KeyError -> 404
    return service.store.filter_events(
        branch_id, after, limit, type, actor, target, tick_from, tick_to
    )


@router.get(
    "/events/{event_id}/trace",
    response_model=m.EventTrace,
    summary="Follow an event's cause chain",
)
async def event_trace(
    event_id: str,
    service: ServiceDependency,
    direction: Literal["back", "forward"] = "back",
    depth: int = Query(5, ge=1, le=20),
):
    """`back`: what caused this event (its causal_refs, recursively). `forward`: what it
    caused (events citing it, recursively). Events from the same action are included."""
    return branching.trace(service.store, event_id, direction, depth)


@router.get(
    "/history/snapshots", response_model=list[m.SnapshotMetadata], summary="List saved checkpoints"
)
async def snapshots(service: ServiceDependency, branch_id: str):
    return service.store.list_snapshots(branch_id)


@router.get(
    "/history/snapshots/{snapshot_id}", response_model=m.WorldUpdate, summary="Read a saved world"
)
async def snapshot(snapshot_id: str, service: ServiceDependency):
    return service.update(service.store.restore(snapshot_id))


@router.get("/branches", response_model=list[m.BranchMetadata], summary="List timelines")
async def branches(service: ServiceDependency):
    return service.store.list_branches()


@router.post(
    "/branches", response_model=m.BranchMetadata, status_code=201, summary="Fork a saved checkpoint"
)
async def fork(body: m.BranchRequest, service: ServiceDependency):
    """Optional `intervention` text is parsed and queued on the fork's next day."""
    async with service.lock:
        return await service.fork(body.snapshot_id, body.name, body.intervention)


@router.get(
    "/branches/compare",
    response_model=m.BranchComparison,
    summary="Compare timelines' metrics day by day",
)
async def compare(
    service: ServiceDependency,
    ids: list[str] = Query(..., min_length=1, max_length=4, description="Branch IDs"),
    stride: int = Query(1, ge=1, le=365, description="Days between points"),
):
    """Per-branch series of bread price, wealth gap (Gini), population, total money and top
    influence, including each fork's shared history before it split. Aligned by tick."""
    return branching.compare(service.store, ids, stride)


@router.get(
    "/branches/divergence",
    response_model=m.Divergence,
    summary="Find where two timelines first decided differently",
)
async def divergence(
    service: ServiceDependency,
    a: str,
    b: str,
    depth: int = Query(3, ge=1, le=10, description="Forward cause-chain depth"),
):
    """After the shared history, the first decision (player or citizen action) that
    differs, with each timeline's forward cause chain from it."""
    return branching.divergence(service.store, a, b, depth)


@router.post(
    "/branches/{branch_id}/activate",
    response_model=m.WorldUpdate,
    summary="Switch the active timeline",
)
async def activate(branch_id: str, service: ServiceDependency):
    async with service.lock:
        run = service.runs.get(branch_id)
        if run is not None and run.status == "running":
            raise HTTPException(409, "This branch is running in the background; stop it first")
        state = service.store.world(branch_id)
        service.store.activate(branch_id)
        service.state, service.playing = state, False
        service.branch_epoch += 1
        if service.decision_task is not None:
            service.decision_task.cancel()
        result = service.update()
        await service.broadcast(result)
        return result


@router.get(
    "/branches/{branch_id}/world",
    response_model=m.WorldUpdate,
    summary="Read a timeline's latest state",
)
async def branch_world(branch_id: str, service: ServiceDependency):
    return service.update(service.store.world(branch_id))


@router.get(
    "/branches/{branch_id}/hashes",
    response_model=list[m.TickHash],
    summary="World hash at the end of every day",
)
async def branch_hashes(branch_id: str, service: ServiceDependency):
    """Determinism evidence: the same seed and the same actions give the same hashes, so
    two timelines agree up to the first day their hashes differ."""
    return branching.hashes(service.store, branch_id)


@router.get(
    "/branches/{branch_id}/checkpoints",
    response_model=list[m.Checkpoint],
    summary="Yearly fork points",
)
async def branch_checkpoints(branch_id: str, service: ServiceDependency):
    """The last snapshot of each simulated year (`KRONOS_TICKS_PER_YEAR` days)."""
    service.store.branch(branch_id)  # KeyError -> 404
    return branching.checkpoints(service.store, branch_id, service.config.ticks_per_year)


@router.post(
    "/branches/{branch_id}/run",
    response_model=m.HeadlessRun,
    status_code=202,
    summary="Run a timeline in the background",
)
async def run_branch(branch_id: str, body: m.HeadlessRunRequest, service: ServiceDependency):
    """Advance a non-active branch `ticks` days at full speed, off screen, while the live
    branch keeps running. Citizens decide with the free utility policy (or not at all)."""
    async with service.lock:
        return service.start_run(branch_id, body)


@router.get(
    "/branches/{branch_id}/run",
    response_model=m.HeadlessRun,
    summary="Progress of a background run",
)
async def run_status(branch_id: str, service: ServiceDependency):
    if branch_id not in service.runs:
        raise KeyError("No run for this branch")
    return service.runs[branch_id]


@router.delete(
    "/branches/{branch_id}/run",
    response_model=m.HeadlessRun,
    summary="Stop a background run",
)
async def stop_branch(branch_id: str, service: ServiceDependency):
    return await service.stop_run(branch_id)


@router.get(
    "/agents/{citizen_id}/history",
    response_model=list[m.SimulationEvent],
    summary="Read events a citizen took part in",
)
async def citizen_history(
    citizen_id: str,
    service: ServiceDependency,
    branch_id: str | None = None,
    through: int | None = None,
    limit: int = Query(100, ge=1, le=500),
):
    """Events where the citizen is the actor, sender, recipient, or subject; oldest first.

    Defaults to the active branch.
    """
    branch_id = branch_id or service.state.branch_id
    if citizen_id not in service.store.world(branch_id).citizens:
        raise KeyError("Unknown citizen")
    return service.store.list_citizen_events(branch_id, citizen_id, through, limit)


@router.get(
    "/actions/{action_id}",
    response_model=m.ActionResult,
    summary="Read the outcome of an agent action",
)
async def action_result(action_id: str, service: ServiceDependency):
    """Read an attempt in this API session; committed Events survive restarts."""
    return service.action_result(action_id)
