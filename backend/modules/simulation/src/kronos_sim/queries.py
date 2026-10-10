"""Read-only views derived from a world. Used by API routes and the agent layer alike."""

from kronos_sim import models as m
from kronos_sim.engine import SUPPORTED_ACTIONS

# Wealth tiers in cents, tuned for the current seed (spec: rich >= 1,000 florins, middle >= 300).
RICH_CENTS = 10000
MIDDLE_CENTS = 3000


def wealth_tier(money: int) -> m.WealthTier:
    return "rich" if money >= RICH_CENTS else "middle" if money >= MIDDLE_CENTS else "poor"


def profile(state: m.WorldState, citizen_id: str) -> m.CitizenProfile:
    citizen = state.citizens.get(citizen_id)
    if citizen is None:
        raise KeyError("Unknown citizen")
    owned = sorted(b.id for b in state.buildings.values() if b.owner_id == citizen_id)
    return m.CitizenProfile(
        citizen=citizen.model_copy(deep=True),
        role="business_owner" if owned else "commoner",
        wealth_tier=wealth_tier(citizen.money),
        employed=citizen.employer_id in state.buildings,
        owned_building_ids=owned,
    )


def observe(state: m.WorldState, citizen_id: str) -> m.AgentObservation:
    """The single observation builder for routes, /decide, and the tick loop."""
    view = profile(state, citizen_id)
    return m.AgentObservation(
        branch_id=state.branch_id,
        tick=state.tick,
        sequence=state.sequence,
        citizen=view.citizen,
        role=view.role,
        wealth_tier=view.wealth_tier,
        bread_prices={
            b.id: b.prices["bread"] for b in state.buildings.values() if b.kind == "bakery"
        },
        neighbors={
            c.id: c.name
            for c in sorted(state.citizens.values(), key=lambda c: c.id)
            if c.id != citizen_id
        },
        available_actions=list(SUPPORTED_ACTIONS),
        loans=[
            loan
            for loan in loans(state, citizen_id)
            if loan.status in ("offered", "active", "defaulted")
        ],
        incoming_offers=offers(state, citizen_id).incoming,
    )


def offers(state: m.WorldState, citizen_id: str) -> m.AgentOffers:
    """Pending offers to and from a citizen, in offer ID order."""
    if citizen_id not in state.citizens:
        raise KeyError("Unknown citizen")
    pending = [state.trade_offers[oid].model_copy(deep=True) for oid in sorted(state.trade_offers)]
    return m.AgentOffers(
        citizen_id=citizen_id,
        incoming=[o for o in pending if o.recipient_id == citizen_id],
        outgoing=[o for o in pending if o.offerer_id == citizen_id],
    )


def _summary(resource: str, prices: list[int]) -> m.MarketPrice:
    """Average is the mean in integer cents, rounded half up."""
    total, count = sum(prices), len(prices)
    return m.MarketPrice(
        resource=resource,
        average=(2 * total + count) // (2 * count),
        min=min(prices),
        max=max(prices),
        sellers=count,
    )


def market_prices(state: m.WorldState) -> m.MarketPrices:
    """Each good priced by at least one building, averaged over the buildings that price it."""
    by_resource: dict[str, list[int]] = {}
    for bid in sorted(state.buildings):
        for resource, price in state.buildings[bid].prices.items():
            by_resource.setdefault(resource, []).append(price)
    return m.MarketPrices(
        branch_id=state.branch_id,
        tick=state.tick,
        sequence=state.sequence,
        prices=[_summary(r, by_resource[r]) for r in sorted(by_resource)],
    )


# Events that can change a good's market price; the store prefilters on these.
PRICE_EVENT_TYPES = ("price_changed", "building_constructed", "building_removed")


def price_history(
    start: m.WorldState, events: list[m.SimulationEvent], resource: str
) -> m.PriceHistory:
    """Replay price-affecting events (sequence order) over a starting world.

    One point for the start, then one per event that changes the summary. New buildings
    start at the Building default prices, matching the engine.
    """
    prices = {bid: dict(b.prices) for bid, b in start.buildings.items()}
    default = m.Building.model_fields["prices"].default_factory()
    points: list[m.PricePoint] = []

    def record(tick: int, sequence: int):
        listed = [p[resource] for _, p in sorted(prices.items()) if resource in p]
        if not listed:
            return
        summary = _summary(resource, listed).model_dump(exclude={"resource"})
        if points and points[-1].model_dump(exclude={"tick", "sequence"}) == summary:
            return
        points.append(m.PricePoint(tick=tick, sequence=sequence, **summary))

    record(start.tick, start.sequence)
    for event in events:
        if event.sequence <= start.sequence:
            continue
        if event.type == "price_changed":
            prices.setdefault(event.payload.building_id, {})[event.payload.resource] = (
                event.payload.new_price
            )
        elif event.type == "building_constructed":
            prices[event.payload.entity_id] = dict(default)
        elif event.type == "building_removed":
            prices.pop(event.payload.entity_id, None)
        else:
            continue
        record(event.tick, event.sequence)
    return m.PriceHistory(branch_id=start.branch_id, resource=resource, points=points)


def business_profile(state: m.WorldState, building_id: str) -> m.BusinessProfile:
    building = state.buildings.get(building_id)
    if building is None:
        raise KeyError("Unknown business")
    staff = sorted(c.id for c in state.citizens.values() if c.employer_id == building_id)
    return m.BusinessProfile(
        building=building.model_copy(deep=True),
        employee_ids=staff,
        free_slots=max(0, building.job_slots - len(staff)),
    )


def resource_stocks(state: m.WorldState) -> list[m.ResourceStock]:
    return [state.resources[kind].model_copy() for kind in sorted(state.resources)]


def job_openings(state: m.WorldState) -> list[m.JobOpening]:
    """Businesses with at least one free slot, in building ID order."""
    applications = sorted(state.job_applications.values(), key=lambda a: a.sequence)
    openings = []
    for building_id in sorted(state.buildings):
        view = business_profile(state, building_id)
        if view.free_slots < 1:
            continue
        building = view.building
        openings.append(
            m.JobOpening(
                building_id=building.id,
                name=building.name,
                kind=building.kind,
                owner_id=building.owner_id,
                plot_id=building.plot_id,
                position=building.position,
                wage=building.wage,
                free_slots=view.free_slots,
                applicant_ids=[a.citizen_id for a in applications if a.building_id == building.id],
            )
        )
    return openings


def loans(
    state: m.WorldState, citizen_id: str | None = None, status: m.LoanStatus | None = None
) -> list[m.Loan]:
    """Loans in ID order, optionally where citizen_id lends or borrows, and by status."""
    return [
        loan.model_copy(deep=True)
        for _, loan in sorted(state.loans.items())
        if (citizen_id is None or citizen_id in (loan.lender_id, loan.borrower_id))
        and (status is None or loan.status == status)
    ]
