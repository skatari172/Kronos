"""Citizen-agent tools. Agent identity is explicit in the route and proposal."""

from fastapi import APIRouter
from kronos_sim import models as m

from kronos.dependencies import ServiceDependency

router = APIRouter(prefix="/api/agents", tags=["Agent tools"])


@router.get(
    "/{citizen_id}/observation",
    response_model=m.AgentObservation,
    summary="Read a citizen's current observation",
)
async def observation(citizen_id: str, service: ServiceDependency):
    """Read personal state and public bakery prices without advancing the simulation."""
    async with service.lock:
        state = service.state
        citizen = state.citizens.get(citizen_id)
        if citizen is None:
            raise KeyError("Unknown citizen")
        return m.AgentObservation(
            branch_id=state.branch_id,
            tick=state.tick,
            sequence=state.sequence,
            citizen=citizen.model_copy(deep=True),
            bread_prices={
                b.id: b.prices["bread"] for b in state.buildings.values() if b.kind == "bakery"
            },
        )


@router.post(
    "/{citizen_id}/actions/validate",
    response_model=m.ActionValidationResult,
    summary="Validate an agent proposal without committing it",
)
async def validate(citizen_id: str, body: m.ActionRequest, service: ServiceDependency):
    """Dry-run against a copied world. Saves no events, state, snapshots, or RNG changes.

    Validation is only valid for the returned sequence; execution rechecks that version.
    """
    return await service.validate_action(body, citizen_id)


@router.post(
    "/{citizen_id}/actions",
    response_model=m.ActionResult,
    summary="Submit an agent action for engine execution",
)
async def execute(citizen_id: str, body: m.ActionRequest, service: ServiceDependency):
    """Require actor_id to match citizen_id, then validate, persist, and broadcast.

    A rule rejection returns status "rejected" with an error code, and is saved as an
    action_rejected event plus a memory for the agent. Stale versions still return 409.
    Agents never mutate live state themselves; the full world arrives on WS /ws/world.
    """
    return await service.submit_agent_action(body, citizen_id)
