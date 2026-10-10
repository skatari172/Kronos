"""Shared world queries and the live update stream."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from kronos_sim import models as m
from kronos_sim.queries import job_openings, profile

from kronos.dependencies import ServiceDependency

router = APIRouter(tags=["World"])


@router.get("/api/world", response_model=m.WorldUpdate, summary="Read the active world")
async def world(service: ServiceDependency):
    return service.update()


@router.get(
    "/api/agents", response_model=list[m.CitizenProfile], summary="List citizens with filters"
)
async def agents(
    service: ServiceDependency,
    role: m.Role | None = None,
    employed: bool | None = None,
    wealth_tier: m.WealthTier | None = None,
):
    async with service.lock:
        state = service.state
        profiles = [profile(state, citizen_id) for citizen_id in sorted(state.citizens)]
    return [
        p
        for p in profiles
        if (role is None or p.role == role)
        and (employed is None or p.employed == employed)
        and (wealth_tier is None or p.wealth_tier == wealth_tier)
    ]


@router.get(
    "/api/agents/{citizen_id}",
    response_model=m.CitizenProfile,
    summary="Read one citizen's full state",
)
async def agent(citizen_id: str, service: ServiceDependency):
    async with service.lock:
        return profile(service.state, citizen_id)


@router.get("/api/jobs", response_model=list[m.JobOpening], summary="List open job slots")
async def jobs(service: ServiceDependency, kind: m.BuildingKind | None = None, min_wage: int = 0):
    """Businesses with a free slot, their wage, location, and pending applicants.

    Apply with POST /api/agents/{id}/apply; the owner answers by hire or reject_application,
    otherwise the next tick resolves the application automatically.
    """
    async with service.lock:
        openings = job_openings(service.state)
    return [o for o in openings if (kind is None or o.kind == kind) and o.wage >= min_wage]


@router.websocket("/ws/world")
async def websocket(socket: WebSocket):
    await socket.accept()
    service = socket.app.state.service
    try:
        async with service.lock:
            await socket.send_json(service.update().model_dump(mode="json"))
            service.clients.add(socket)
        while True:
            await socket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        service.clients.discard(socket)
