"""Market prices and citizen-to-citizen trade offers.

Prices are averaged over every building that lists the good. Trades are two agent
actions: the offerer's trade creates a pending offer, and the recipient's respond_trade
accepts (both sides are rechecked, then swapped) or declines it. Unanswered offers expire.
"""

from fastapi import APIRouter
from kronos_sim import models as m
from kronos_sim.queries import PRICE_EVENT_TYPES, market_prices, offers, price_history

from kronos.dependencies import ServiceDependency

router = APIRouter(prefix="/api")


async def submit(service, body: m.BusinessCommand, action: m.AgentAction) -> m.ActionResult:
    request = m.ActionRequest(
        branch_id=body.branch_id, expected_sequence=body.expected_sequence, action=action
    )
    return await service.submit_agent_action(request, body.actor_id)


@router.get(
    "/market/prices",
    response_model=m.MarketPrices,
    tags=["World"],
    summary="Read current prices per good",
)
async def prices(service: ServiceDependency, branch_id: str | None = None):
    """Average (integer cents, rounded half up), min, max, and seller count per good.

    Defaults to the active branch.
    """
    if branch_id is None or branch_id == service.state.branch_id:
        async with service.lock:
            return market_prices(service.state)
    return market_prices(service.store.world(branch_id))


@router.get(
    "/market/prices/history",
    response_model=m.PriceHistory,
    tags=["History"],
    summary="Read a good's price series",
)
async def history(service: ServiceDependency, good: m.TradedResource, branch_id: str | None = None):
    """Rebuilt from the branch's first checkpoint plus its saved price-affecting events.

    One point at the branch start, then one per event that changed the average, min, max,
    or seller count. Defaults to the active branch.
    """
    branch_id = branch_id or service.state.branch_id
    start = service.store.first_snapshot(branch_id)
    events = service.store.list_events_of_types(branch_id, PRICE_EVENT_TYPES, start.sequence)
    return price_history(start, events, good)


@router.get(
    "/agents/{citizen_id}/offers",
    response_model=m.AgentOffers,
    tags=["Agent tools"],
    summary="Read a citizen's pending trade offers",
)
async def agent_offers(citizen_id: str, service: ServiceDependency):
    """Incoming offers are also part of the citizen's observation."""
    async with service.lock:
        return offers(service.state, citizen_id)


@router.post(
    "/market/trade",
    response_model=m.ActionResult,
    tags=["Agent tools"],
    summary="Offer a trade to another citizen",
)
async def trade(body: m.TradeRequest, service: ServiceDependency):
    """The offerer (actor_id) must hold what it gives now; nothing moves until accepted."""
    action = m.Trade(
        actor_id=body.actor_id,
        rationale=body.rationale,
        recipient_id=body.recipient_id,
        give=body.give,
        get=body.get,
    )
    return await submit(service, body, action)


@router.post(
    "/market/trade/{offer_id}/respond",
    response_model=m.ActionResult,
    tags=["Agent tools"],
    summary="Accept or decline a trade offer (recipient only)",
)
async def respond(offer_id: str, body: m.RespondTradeRequest, service: ServiceDependency):
    """Accepting rechecks that both sides still hold their goods, then swaps them."""
    action = m.RespondTrade(
        actor_id=body.actor_id, rationale=body.rationale, offer_id=offer_id, accept=body.accept
    )
    return await submit(service, body, action)
