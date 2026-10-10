"""Player tools: natural-language interventions and explicit citizen actions."""

from fastapi import APIRouter
from kronos_sim import models as m
from kronos_sim.engine import Engine

from kronos.dependencies import ServiceDependency

router = APIRouter(prefix="/api", tags=["User tools"])


@router.post(
    "/interventions",
    response_model=m.InterventionResult,
    summary="Apply a natural-language intervention",
)
async def intervene(body: m.InterventionRequest, service: ServiceDependency):
    """Parse supported text, validate the current version, then persist and broadcast."""
    command = await service.agents.parse(body.text)
    async with service.lock:
        service.check(body)
        result = await service.commit(Engine(service.state).intervene(command, body.text))
        return m.InterventionResult(command=command, update=result)


@router.post("/actions", response_model=m.WorldUpdate, summary="Execute a player-directed action")
async def action(body: m.ActionRequest, service: ServiceDependency):
    """Buy, sell, transfer, price, produce, consume, communicate, build, upgrade, or move.

    The player chooses actor_id; the engine still enforces ownership, funds, and stock.
    """
    return await service.execute_action(body)
