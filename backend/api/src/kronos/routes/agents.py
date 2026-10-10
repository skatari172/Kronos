"""Citizen-agent tools. Agent identity is explicit in the route and proposal."""

from fastapi import APIRouter
from kronos_sim import models as m
from kronos_sim.queries import observe

from kronos.dependencies import ServiceDependency

router = APIRouter(prefix="/api/agents", tags=["Agent tools"])


@router.get(
    "/{citizen_id}/observation",
    response_model=m.AgentObservation,
    summary="Read a citizen's current observation",
)
async def observation(citizen_id: str, service: ServiceDependency):
    """Own state, role, public bakery prices, neighbor names, and runnable action types.

    Read-only; this is the same observation /decide sends to the AI provider.
    """
    async with service.lock:
        return observe(service.state, citizen_id)


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


@router.post(
    "/{citizen_id}/decide",
    response_model=m.DecisionResult,
    summary="Let the AI layer choose and submit this citizen's next action",
)
async def decide(citizen_id: str, body: m.MutationRequest, service: ServiceDependency):
    """Observation → provider → the same path as POST /actions (logged even if rejected).

    Returns 409 if the world changed while the provider was thinking, and 422 if the provider
    fails or times out.
    """
    return await service.decide(citizen_id, body)


@router.post(
    "/{citizen_id}/ask",
    response_model=m.AskResult,
    summary="Ask a citizen a question, answered from its own event history",
)
async def ask(citizen_id: str, body: m.AskRequest, service: ServiceDependency):
    """Read-only. Answers may only cite events in which this citizen took part."""
    return await service.ask(citizen_id, body.question)


@router.patch(
    "/{citizen_id}/goals",
    response_model=m.ActionResult,
    summary="Shift a citizen's goal weights by at most 10 points each",
)
async def goals(citizen_id: str, body: m.GoalsUpdateRequest, service: ServiceDependency):
    """Submitted as an adjust_goals action; weights are clamped and renormalised to 100."""
    action = m.AdjustGoals(actor_id=citizen_id, changes=body.changes, rationale=body.rationale)
    request = m.ActionRequest(
        branch_id=body.branch_id, expected_sequence=body.expected_sequence, action=action
    )
    return await service.submit_agent_action(request, citizen_id)


@router.post(
    "/{citizen_id}/gather",
    response_model=m.ActionResult,
    summary="Gather from a shared natural stock into the citizen's employer",
)
async def gather(citizen_id: str, body: m.GatherRequest, service: ServiceDependency):
    """Submitted as a gather_resource action at the citizen's current employer.

    The employer must match the resource (wheat: farm). Takes up to quantity; a nearly empty
    stock gives a partial gather, and an empty one is rejected as out_of_stock.
    """
    async with service.lock:
        citizen = service.state.citizens.get(citizen_id)
        if citizen is None:
            raise KeyError("Unknown citizen")
        employer = citizen.employer_id or ""  # Unemployed: the engine rejects with bad_params.
    action = m.GatherResource(
        actor_id=citizen_id,
        building_id=employer,
        resource=body.resource,
        quantity=body.quantity,
        rationale=body.rationale,
    )
    request = m.ActionRequest(
        branch_id=body.branch_id, expected_sequence=body.expected_sequence, action=action
    )
    return await service.submit_agent_action(request, citizen_id)


@router.post(
    "/{citizen_id}/apply",
    response_model=m.ActionResult,
    summary="Apply for a job at a business",
)
async def apply(citizen_id: str, body: m.ApplyJobRequest, service: ServiceDependency):
    """Submitted as an apply_job action. Requires being unemployed and a free slot.

    The owner accepts (hire) or rejects (reject_application); unanswered applications are
    resolved on the next tick: hired if a slot is free and the wage is covered, else rejected.
    """
    action = m.ApplyJob(actor_id=citizen_id, building_id=body.business_id, rationale=body.rationale)
    request = m.ActionRequest(
        branch_id=body.branch_id, expected_sequence=body.expected_sequence, action=action
    )
    return await service.submit_agent_action(request, citizen_id)


@router.post("/{citizen_id}/quit", response_model=m.ActionResult, summary="Quit the current job")
async def quit_job(citizen_id: str, body: m.QuitJobRequest, service: ServiceDependency):
    """Submitted as a quit_job action; emits employment_changed."""
    action = m.QuitJob(actor_id=citizen_id, rationale=body.rationale)
    request = m.ActionRequest(
        branch_id=body.branch_id, expected_sequence=body.expected_sequence, action=action
    )
    return await service.submit_agent_action(request, citizen_id)
