"""Invention reads and research, licensing, and adoption routes.

Each mutation is one agent action for body.actor_id; results and logged rejections
match POST /api/agents/{id}/actions.
"""

from fastapi import APIRouter
from kronos_sim import models as m

from kronos.dependencies import ServiceDependency

router = APIRouter(prefix="/api/inventions")


async def submit(service, body: m.BusinessCommand, action: m.AgentAction) -> m.ActionResult:
    request = m.ActionRequest(
        branch_id=body.branch_id, expected_sequence=body.expected_sequence, action=action
    )
    return await service.submit_agent_action(request, body.actor_id)


def common(body: m.BusinessCommand) -> dict:
    return {"actor_id": body.actor_id, "rationale": body.rationale}


@router.get("", response_model=list[m.Invention], tags=["World"], summary="List inventions")
async def inventions(service: ServiceDependency):
    async with service.lock:
        state = service.state
        return [state.inventions[iid].model_copy(deep=True) for iid in sorted(state.inventions)]


@router.get(
    "/license-offers",
    response_model=list[m.LicenseOffer],
    tags=["World"],
    summary="List pending license offers",
)
async def license_offers(service: ServiceDependency, recipient: str | None = None):
    """Offers expire at the end of the tick they were made in."""
    async with service.lock:
        offers = service.state.license_offers
        return [
            offers[oid].model_copy()
            for oid in sorted(offers)
            if recipient is None or offers[oid].recipient_id == recipient
        ]


@router.get(
    "/{invention_id}", response_model=m.Invention, tags=["World"], summary="Read one invention"
)
async def invention(invention_id: str, service: ServiceDependency):
    async with service.lock:
        found = service.state.inventions.get(invention_id)
        if found is None:
            raise KeyError("Unknown invention")
        return found.model_copy(deep=True)


@router.post(
    "/{invention_id}/research",
    response_model=m.ActionResult,
    tags=["Agent tools"],
    summary="Research an invention with money or wage time",
)
async def research(invention_id: str, body: m.ResearchRequest, service: ServiceDependency):
    """Money mode spends `amount` (capped at what is left). Time mode forfeits the actor's wage
    for `ticks` days, each counting as progress. At full cost the top contributor owns it."""
    action = m.Research(
        **common(body),
        invention_id=invention_id,
        mode=body.mode,
        amount=body.amount,
        ticks=body.ticks,
    )
    return await submit(service, body, action)


@router.post(
    "/{invention_id}/license",
    response_model=m.ActionResult,
    tags=["Agent tools"],
    summary="Offer a license (invention owner only)",
)
async def license_invention(invention_id: str, body: m.LicenseRequest, service: ServiceDependency):
    """Creates an offer; no money moves until the recipient accepts on the same tick."""
    action = m.LicenseInvention(
        **common(body), invention_id=invention_id, recipient_id=body.recipient_id, fee=body.fee
    )
    return await submit(service, body, action)


@router.post(
    "/license-offers/{offer_id}/respond",
    response_model=m.ActionResult,
    tags=["Agent tools"],
    summary="Accept or decline a license offer (recipient only)",
)
async def respond_license(
    offer_id: str, body: m.LicenseResponseRequest, service: ServiceDependency
):
    """Accepting re-checks funds and moves the fee from the recipient to the owner."""
    action = m.RespondLicense(**common(body), offer_id=offer_id, accept=body.accept)
    return await submit(service, body, action)


@router.post(
    "/{invention_id}/adopt",
    response_model=m.ActionResult,
    tags=["Agent tools"],
    summary="Adopt an invention at a business (business owner with rights)",
)
async def adopt(invention_id: str, body: m.AdoptRequest, service: ServiceDependency):
    """Requires an unlocked invention, ownership or a license, and business cash for the
    adoption cost. The production effect applies from the next production run."""
    action = m.AdoptInvention(
        **common(body), invention_id=invention_id, building_id=body.building_id
    )
    return await submit(service, body, action)
