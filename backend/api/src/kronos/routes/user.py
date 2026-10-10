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


@router.post(
    "/user/query",
    response_model=m.UserQueryResult,
    summary="Process player prompt and execute determined toolkit endpoint",
)
async def user_query(body: m.UserQueryRequest, service: ServiceDependency):
    """Translates player natural language prompt via LLM into the best toolkit endpoint,
    then executes it against the simulation.
    """
    return await service.handle_user_query(body)


@router.post(
    "/query",
    response_model=m.UserQueryResult,
    include_in_schema=False,
)
async def query_alias(body: m.UserQueryRequest, service: ServiceDependency):
    return await service.handle_user_query(body)
