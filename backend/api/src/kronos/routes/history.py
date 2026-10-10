"""Shared historical queries and branch tools."""

from fastapi import APIRouter, Query
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
    return service.store.list_events_after(service.state.branch_id, after, limit)


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
    async with service.lock:
        return await service.fork(body.snapshot_id, body.name)


@router.post(
    "/branches/{branch_id}/activate",
    response_model=m.WorldUpdate,
    summary="Switch the active timeline",
)
async def activate(branch_id: str, service: ServiceDependency):
    async with service.lock:
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
