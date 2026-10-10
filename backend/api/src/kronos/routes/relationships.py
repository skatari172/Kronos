"""Relationship reads and the interact convenience route (agents-api.md section 5.2).

A tie is directed: A's entry for B is how A feels about B. Trust is -100..100, grudge 0..100.
"""

from fastapi import APIRouter
from kronos_sim import models as m
from kronos_sim.queries import relationship_pair, relationships

from kronos.dependencies import ServiceDependency

router = APIRouter()


@router.get(
    "/api/agents/{citizen_id}/relationships",
    response_model=list[m.RelationshipView],
    tags=["World"],
    summary="List a citizen's relationships",
)
async def agent_relationships(citizen_id: str, service: ServiceDependency):
    """How this citizen feels about each citizen it knows, by trust (highest first)."""
    async with service.lock:
        return relationships(service.state, citizen_id)


@router.get(
    "/api/relationships/{a_id}/{b_id}",
    response_model=m.RelationshipPair,
    tags=["World"],
    summary="Read one tie in both directions",
)
async def relationship(a_id: str, b_id: str, service: ServiceDependency):
    """a_to_b is a's trust, grudge and type toward b; b_to_a the reverse.

    A direction without an entry is neutral (trust 0, acquaintance) with known false.
    """
    async with service.lock:
        return relationship_pair(service.state, a_id, b_id)


@router.post(
    "/api/agents/{citizen_id}/interact",
    response_model=m.ActionResult,
    tags=["Agent tools"],
    summary="Befriend, gift, ally, argue, insult, betray or mentor another citizen",
)
async def interact(citizen_id: str, body: m.InteractRequest, service: ServiceDependency):
    """Submitted as an interact action; effects are fixed engine rules.

    The target's feeling toward the actor changes (ally and argue change both directions).
    gift moves amount cents to the target; ally needs the target's trust >= 50; insult costs
    the target 2 reputation, betray costs the actor 10, mentor gives the target 2. One
    interaction per pair per tick.
    """
    action = m.Interact(
        actor_id=citizen_id,
        recipient_id=body.target_id,
        kind=body.kind,
        amount=body.amount,
        rationale=body.rationale,
    )
    request = m.ActionRequest(
        branch_id=body.branch_id, expected_sequence=body.expected_sequence, action=action
    )
    return await service.submit_agent_action(request, citizen_id)
