"""Player tools: natural-language interventions and explicit citizen actions."""

from fastapi import APIRouter
from kronos_sim import models as m

from kronos.dependencies import ServiceDependency

router = APIRouter(prefix="/api", tags=["User tools"])


@router.post(
    "/interventions",
    response_model=m.InterventionResult,
    summary="Apply a natural-language intervention",
)
async def intervene(body: m.InterventionRequest, service: ServiceDependency):
    """Parse supported text and queue it for the next authoritative tick."""
    return await service.intervene(body)
    """Parse supported text, validate the current version, then persist and broadcast."""
    citizens = {cid: c.name for cid, c in service.state.citizens.items()}
    command = await service.agents.parse(body.text, citizens)
    async with service.lock:
        service.check(body)
        result = await service.commit(Engine(service.state).intervene(command, body.text))
        return m.InterventionResult(command=command, update=result)


@router.post("/actions", response_model=m.ActionResult, summary="Queue a player-directed action")
async def action(body: m.ActionRequest, service: ServiceDependency):
    """Buy, sell, transfer, price, produce, consume, communicate, build, upgrade, or move.

    The player chooses actor_id; the engine still enforces ownership, funds, and stock.
    """
    return await service.execute_action(body)


@router.post(
    "/agents",
    response_model=m.SpawnResult,
    status_code=201,
    summary="Spawn a citizen (setup or intervention)",
)
async def spawn(body: m.SpawnCitizenRequest, service: ServiceDependency):
    """Adds a citizen on a plot. Starting money enters the economy from outside."""
    return await service.spawn(body)
