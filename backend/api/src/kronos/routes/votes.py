"""Roles, influence, and the town vote. Proposals and ballots are agent actions.

The acting citizen is body.actor_id; results and logged rejections match
POST /api/agents/{id}/actions.
"""

from typing import Literal

from fastapi import APIRouter
from kronos_sim import models as m
from kronos_sim.queries import influence, roles, votes

from kronos.dependencies import ServiceDependency

router = APIRouter()


async def submit(service, body: m.MutationRequest, action: m.AgentAction) -> m.ActionResult:
    request = m.ActionRequest(
        branch_id=body.branch_id, expected_sequence=body.expected_sequence, action=action
    )
    return await service.submit_agent_action(request, action.actor_id)


@router.get(
    "/api/roles",
    response_model=list[m.RoleInfo],
    tags=["World"],
    summary="Roles and the permission matrix",
)
async def role_matrix():
    """Roles are derived: a citizen who owns a building is a business_owner."""
    return roles()


@router.get(
    "/api/agents/{citizen_id}/influence",
    response_model=m.InfluenceBreakdown,
    tags=["World"],
    summary="Influence breakdown for one citizen",
)
async def agent_influence(citizen_id: str, service: ServiceDependency):
    """0.5 * wealth share + 0.3 * reputation + 0.2 * trust from others, in basis points."""
    async with service.lock:
        return influence(service.state, citizen_id)


@router.get(
    "/api/votes",
    response_model=list[m.VoteView],
    tags=["World"],
    summary="Town votes with influence-weighted tallies",
)
async def vote_list(
    service: ServiceDependency, status: Literal["open", "passed", "failed"] | None = None
):
    async with service.lock:
        return votes(service.state, status)


@router.post(
    "/api/votes", response_model=m.ActionResult, tags=["Agent tools"], summary="Propose a town vote"
)
async def propose(body: m.VoteProposalRequest, service: ServiceDependency):
    """One open vote at a time, at most one new vote every 10 days; it closes after 3 days."""
    action = m.ProposeVote(
        actor_id=body.actor_id, rationale=body.rationale, kind=body.kind, value=body.value
    )
    return await submit(service, body, action)


@router.post(
    "/api/votes/{vote_id}/ballot",
    response_model=m.ActionResult,
    tags=["Agent tools"],
    summary="Cast or change a ballot",
)
async def ballot(vote_id: str, body: m.BallotRequest, service: ServiceDependency):
    action = m.CastVote(
        actor_id=body.actor_id, rationale=body.rationale, vote_id=vote_id, choice=body.choice
    )
    return await submit(service, body, action)
