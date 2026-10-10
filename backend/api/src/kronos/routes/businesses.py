"""Business reads and convenience routes. Each mutation is one agent action.

The acting citizen is body.actor_id; results and logged rejections match
POST /api/agents/{id}/actions.
"""

from fastapi import APIRouter
from kronos_sim import models as m
from kronos_sim.queries import business_profile

from kronos.dependencies import ServiceDependency

router = APIRouter(prefix="/api/businesses")


async def submit(service, body: m.BusinessCommand, action: m.AgentAction) -> m.ActionResult:
    request = m.ActionRequest(
        branch_id=body.branch_id, expected_sequence=body.expected_sequence, action=action
    )
    return await service.submit_agent_action(request, body.actor_id)


def common(body: m.BusinessCommand) -> dict:
    return {"actor_id": body.actor_id, "rationale": body.rationale}


@router.get("", response_model=list[m.BusinessProfile], tags=["World"], summary="List businesses")
async def businesses(
    service: ServiceDependency, kind: m.BuildingKind | None = None, owner: str | None = None
):
    async with service.lock:
        state = service.state
        profiles = [business_profile(state, bid) for bid in sorted(state.buildings)]
    return [
        p
        for p in profiles
        if (kind is None or p.building.kind == kind)
        and (owner is None or p.building.owner_id == owner)
    ]


@router.get(
    "/{building_id}",
    response_model=m.BusinessProfile,
    tags=["World"],
    summary="Read one business",
)
async def business(building_id: str, service: ServiceDependency):
    async with service.lock:
        return business_profile(service.state, building_id)


@router.post("", response_model=m.ActionResult, tags=["Agent tools"], summary="Found a business")
async def found(body: m.FoundBusinessRequest, service: ServiceDependency):
    """Capital (at least 5,000 cents) moves from the founder into the new business's cash."""
    action = m.FoundBusiness(
        **common(body), plot_id=body.plot_id, kind=body.kind, capital=body.capital
    )
    return await submit(service, body, action)


@router.post(
    "/{building_id}/close",
    response_model=m.ActionResult,
    tags=["Agent tools"],
    summary="Close a business (owner only)",
)
async def close(building_id: str, body: m.BusinessCommand, service: ServiceDependency):
    """Cash and goods return to the owner, employees are released, and the plot is freed."""
    action = m.CloseBusiness(**common(body), building_id=building_id)
    return await submit(service, body, action)


@router.patch(
    "/{building_id}/price",
    response_model=m.ActionResult,
    tags=["Agent tools"],
    summary="Set a price (owner only)",
)
async def price(building_id: str, body: m.PriceRequest, service: ServiceDependency):
    action = m.SetPrice(
        **common(body), building_id=building_id, resource=body.resource, price=body.price
    )
    return await submit(service, body, action)


@router.patch(
    "/{building_id}/wage",
    response_model=m.ActionResult,
    tags=["Agent tools"],
    summary="Set the daily wage (owner only)",
)
async def wage(building_id: str, body: m.WageRequest, service: ServiceDependency):
    action = m.SetWage(**common(body), building_id=building_id, wage=body.wage)
    return await submit(service, body, action)


@router.post(
    "/{building_id}/hire",
    response_model=m.ActionResult,
    tags=["Agent tools"],
    summary="Hire an unemployed citizen (owner only)",
)
async def hire(building_id: str, body: m.EmployeeRequest, service: ServiceDependency):
    action = m.Hire(**common(body), building_id=building_id, citizen_id=body.citizen_id)
    return await submit(service, body, action)


@router.post(
    "/{building_id}/fire",
    response_model=m.ActionResult,
    tags=["Agent tools"],
    summary="Release an employee (owner only)",
)
async def fire(building_id: str, body: m.EmployeeRequest, service: ServiceDependency):
    action = m.Fire(**common(body), building_id=building_id, citizen_id=body.citizen_id)
    return await submit(service, body, action)


@router.post(
    "/{building_id}/buy",
    response_model=m.ActionResult,
    tags=["Agent tools"],
    summary="Buy goods from a business",
)
async def buy(building_id: str, body: m.PurchaseRequest, service: ServiceDependency):
    action = m.Buy(
        **common(body),
        building_id=building_id,
        resource=body.resource,
        quantity=body.quantity,
        max_unit_price=body.max_unit_price,
    )
    return await submit(service, body, action)
