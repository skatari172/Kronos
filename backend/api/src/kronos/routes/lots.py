"""Lot reads and property convenience routes. Each mutation is one agent action.

The acting citizen is body.actor_id (the tenant for lease and pay, the owner for rent and
evict); results and logged rejections match POST /api/agents/{id}/actions.
"""

from fastapi import APIRouter
from kronos_sim import models as m
from kronos_sim.queries import lot_profile

from kronos.dependencies import ServiceDependency

router = APIRouter(prefix="/api/lots")


async def submit(service, body: m.LotCommand, action: m.AgentAction) -> m.ActionResult:
    request = m.ActionRequest(
        branch_id=body.branch_id, expected_sequence=body.expected_sequence, action=action
    )
    return await service.submit_agent_action(request, body.actor_id)


def common(body: m.LotCommand, plot_id: str) -> dict:
    return {"actor_id": body.actor_id, "rationale": body.rationale, "plot_id": plot_id}


@router.get("", response_model=list[m.LotProfile], tags=["World"], summary="List lots")
async def lots(
    service: ServiceDependency,
    owner: str | None = None,
    tenant: str | None = None,
    use: m.LotUse | None = None,
):
    async with service.lock:
        state = service.state
        profiles = [lot_profile(state, pid) for pid in sorted(state.plots)]
    return [
        p
        for p in profiles
        if (owner is None or p.lot.owner_id == owner)
        and (tenant is None or p.lot.tenant_id == tenant)
        and (use is None or p.use == use)
    ]


@router.get("/{plot_id}", response_model=m.LotProfile, tags=["World"], summary="Read one lot")
async def lot(plot_id: str, service: ServiceDependency):
    async with service.lock:
        return lot_profile(service.state, plot_id)


@router.post(
    "/{plot_id}/lease",
    response_model=m.ActionResult,
    tags=["Agent tools"],
    summary="Lease a vacant lot from its owner",
)
async def lease(plot_id: str, body: m.LotCommand, service: ServiceDependency):
    """actor_id becomes the tenant at the owner's current rent, collected every rent period."""
    return await submit(service, body, m.LeaseLot(**common(body, plot_id)))


@router.patch(
    "/{plot_id}/rent",
    response_model=m.ActionResult,
    tags=["Agent tools"],
    summary="Set the rent (owner only)",
)
async def rent(plot_id: str, body: m.RentRequest, service: ServiceDependency):
    """While leased, each change is limited to 20% of the current rent (at least 100 cents)."""
    return await submit(service, body, m.SetRent(**common(body, plot_id), rent=body.rent))


@router.post(
    "/{plot_id}/pay",
    response_model=m.ActionResult,
    tags=["Agent tools"],
    summary="Pay rent (tenant only)",
)
async def pay(plot_id: str, body: m.LotCommand, service: ServiceDependency):
    """Clears all arrears, or pays one period ahead when nothing is owed."""
    return await submit(service, body, m.PayRent(**common(body, plot_id)))


@router.post(
    "/{plot_id}/evict",
    response_model=m.ActionResult,
    tags=["Agent tools"],
    summary="Evict a tenant 3+ rent periods behind (owner only)",
)
async def evict(plot_id: str, body: m.LotCommand, service: ServiceDependency):
    """Arrears are written off and the tenant's business on the lot is closed."""
    return await submit(service, body, m.Evict(**common(body, plot_id)))
