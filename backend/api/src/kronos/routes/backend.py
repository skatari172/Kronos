"""Simulation controls and tools for backend automation and development clients."""

from uuid import uuid4

from fastapi import APIRouter
from kronos_sim import models as m
from kronos_sim.seed import initial_world

from kronos.dependencies import ServiceDependency

router = APIRouter(tags=["Backend tools"])


@router.get("/health", summary="Check backend health")
async def health(service: ServiceDependency) -> dict[str, str]:
    """The provider is the one actually configured (`KRONOS_LLM_PROVIDER`), not a constant."""
    return {"status": "ok", "provider": service.config.llm_provider}


@router.get(
    "/api/simulation/status", response_model=m.SimulationStatus, summary="Read playback status"
)
async def status(service: ServiceDependency):
    return service.status()


@router.post(
    "/api/simulation/tick",
    response_model=m.SimulationTickResult,
    summary="Advance the simulation by one day",
)
async def tick(body: m.MutationRequest, service: ServiceDependency):
    # Service.tick takes the lock itself so agent proposals are gathered outside it.
    return await service.tick(body)


@router.post(
    "/api/simulation/play", response_model=m.SimulationStatus, summary="Start the simulation clock"
)
async def play(body: m.PlayRequest, service: ServiceDependency):
    async with service.lock:
        service.check(body)
        service.playing, service.speed, service.error = True, body.speed, None
        return service.status()


@router.post(
    "/api/simulation/pause", response_model=m.SimulationStatus, summary="Pause the simulation clock"
)
async def pause(service: ServiceDependency):
    async with service.lock:
        service.playing = False
        return service.status()


@router.post(
    "/api/backend/actions",
    response_model=m.ActionResult,
    summary="Queue a backend automation action",
)
async def action(body: m.ActionRequest, service: ServiceDependency):
    """Use the same version, engine, and persistence checks as other action callers.

    This endpoint grants no extra capabilities. In-process jobs may call
    Service.execute_action directly instead of making an HTTP request to this server.
    """
    return await service.execute_action(body, source="backend")


@router.post(
    "/api/simulations",
    response_model=m.BranchMetadata,
    status_code=201,
    summary="Create an independent village",
)
async def new_simulation(service: ServiceDependency):
    """Persist a new village; explicitly activate its branch to start using it."""
    async with service.lock:
        bid = str(uuid4())
        meta = m.BranchMetadata(id=bid, name="New village")
        service.store.create(initial_world(service.config.seed, bid), meta)
        return meta
