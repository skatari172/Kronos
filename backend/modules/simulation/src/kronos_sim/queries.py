"""Read-only views derived from a world. Used by API routes and the agent layer alike."""

from kronos_sim import models as m
from kronos_sim.engine import MIN_CAPITAL, RESOURCE_SOURCES, SUPPORTED_ACTIONS

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
        influence=influence(state, citizen_id).influence,
    )


# Observation caps keep a prompt near 800 tokens however large the town grows (A5).
OBSERVED_NEIGHBORS = 8
OBSERVED_JOBS = 3
OBSERVED_BUSINESSES = 3
CONSTRUCTION_COST = 5000  # engine: construct_building costs 50 coins


def observe(
    state: m.WorldState, citizen_id: str, events: list[m.SimulationEvent] | None = None
) -> m.AgentObservation:
    """The single observation builder for routes, /decide, and the tick loop."""
    view = profile(state, citizen_id)
    # The full relationship list and the raw memory counts stay out of the prompt: `ties`
    # carries the strongest feelings and `memory_summary` already renders the counts.
    citizen = view.citizen.model_copy(update={"relationships": [], "memory_tally": {}})
    ties = strongest_ties(state, citizen_id)
    actions = available_actions(state, citizen_id)
    # Openings only matter to someone who can apply; best-paid first.
    jobs = (
        sorted(job_openings(state), key=lambda j: (-j.wage, j.building_id))
        if "apply_job" in actions
        else []
    )
    bakeries = sorted(
        (b for b in state.buildings.values() if b.kind == "bakery"),
        key=lambda b: (b.prices["bread"], b.id),
    )[:12]
    return m.AgentObservation(
        branch_id=state.branch_id,
        tick=state.tick,
        sequence=state.sequence,
        citizen=citizen,
        role=view.role,
        wealth_tier=view.wealth_tier,
        bread_prices={b.id: b.prices["bread"] for b in bakeries},
        bread_stock={b.id: b.inventory.bread for b in bakeries},
        neighbors=neighbors(state, citizen_id, [t.citizen_id for t in ties]),
        available_actions=actions,
        recent_events=[
            event.model_copy(deep=True)
            for event in (events or [])
            if (
                event.actor_id == citizen_id
                or citizen_id
                in {
                    event.payload.model_dump().get(key)
                    for key in ("sender_id", "recipient_id", "entity_id", "citizen_id")
                }
            )
        ][-8:],
        loans=[
            loan
            for loan in loans(state, citizen_id)
            if loan.status in ("offered", "active", "defaulted")
        ][:8],
        incoming_offers=offers(state, citizen_id).incoming[:8],
        ties=ties,
        open_jobs=jobs[:OBSERVED_JOBS],
        businesses=[
            business_profile(state, b.id)
            for b in sorted(state.buildings.values(), key=lambda b: b.id)
            if b.owner_id == citizen_id
        ][:OBSERVED_BUSINESSES],
    )


def neighbors(state: m.WorldState, citizen_id: str, first: list[str]) -> dict[str, str]:
    """Up to OBSERVED_NEIGHBORS names: the citizen's strongest ties first, then by ID."""
    others = [c for c in first if c in state.citizens and c != citizen_id]
    others += [c for c in sorted(state.citizens) if c != citizen_id and c not in others]
    return {c: state.citizens[c].name for c in others[:OBSERVED_NEIGHBORS]}


def available_actions(state: m.WorldState, citizen_id: str) -> list[str]:
    """Engine-supported actions this citizen could plausibly take now, in SUPPORTED_ACTIONS order.

    Drops only actions the engine would certainly reject from the citizen's role and state
    (not an owner, nothing to answer, nothing to sell). It narrows the model's menu and its
    output schema; the engine still validates everything that remains.
    """
    me = state.citizens[citizen_id]
    others = len(state.citizens) > 1
    owned = [b for b in state.buildings.values() if b.owner_id == citizen_id]
    owned_ids = {b.id for b in owned}
    employer = state.buildings.get(me.employer_id or "")
    pending = [
        a
        for a in state.job_applications.values()
        if a.status == "pending" and a.building_id in owned_ids
    ]
    staffed = any(c.employer_id in owned_ids for c in state.citizens.values())
    built = {b.plot_id for b in state.buildings.values()}
    buildable = [
        p
        for p in state.plots.values()
        if p.id not in built and (p.owner_id in (None, citizen_id) or p.tenant_id == citizen_id)
    ]
    leasable = [
        p
        for p in state.plots.values()
        if p.owner_id not in (None, citizen_id)
        and p.tenant_id is None
        and p.id not in built
        and me.money >= p.rent
    ]
    my_lots = [p for p in state.plots.values() if p.owner_id == citizen_id]
    loans = state.loans.values()
    inventions = state.inventions.values()
    open_votes = [v for v in state.votes.values() if v.status == "open"]
    rules = {
        "sell": me.inventory.wheat > 0 or me.inventory.bread > 0,
        "transfer_money": me.money > 0 and others,
        "consume": me.inventory.bread > 0,
        "communicate": others,
        "interact": others,
        "trade": others,
        "lend": me.money > 0 and others,
        "construct_building": me.money >= CONSTRUCTION_COST and bool(buildable),
        "found_business": me.money >= MIN_CAPITAL and bool(buildable),
        "set_price": bool(owned),
        "produce": any(b.kind != "market" for b in owned),
        "upgrade_building": any(b.level < 3 for b in owned),
        "close_business": bool(owned),
        "set_wage": bool(owned),
        "hire": bool(pending),
        "reject_application": bool(pending),
        "fire": staffed,
        "apply_job": employer is None
        and any(business_profile(state, b).free_slots > 0 for b in state.buildings),
        "quit_job": employer is not None,
        "gather_resource": employer is not None and employer.kind in RESOURCE_SOURCES.values(),
        "respond_loan": any(
            loan.borrower_id == citizen_id and loan.status == "offered" for loan in loans
        ),
        "repay": any(
            loan.borrower_id == citizen_id and loan.status in ("active", "defaulted")
            for loan in loans
        ),
        "respond_trade": any(o.recipient_id == citizen_id for o in state.trade_offers.values()),
        "research": any(not i.unlocked for i in inventions),
        "license_invention": any(i.unlocked and i.owner_id == citizen_id for i in inventions),
        "respond_license": any(o.recipient_id == citizen_id for o in state.license_offers.values()),
        "adopt_invention": bool(owned) and any(i.unlocked for i in inventions),
        "propose_vote": not open_votes,
        "vote": any(citizen_id not in v.ballots for v in open_votes),
        "lease_lot": bool(leasable),
        "set_rent": bool(my_lots),
        "pay_rent": any(p.tenant_id == citizen_id for p in state.plots.values()),
        "evict": any(p.tenant_id and p.missed_periods >= 3 for p in my_lots),
    }
    return [action for action in SUPPORTED_ACTIONS if rules.get(action, True)]


# Ties shown in an observation; the full list is GET /api/agents/{id}/relationships.
OBSERVED_TIES = 5


def _view(state: m.WorldState, holder: m.Citizen, other_id: str) -> m.RelationshipView:
    relation = next((r for r in holder.relationships if r.citizen_id == other_id), None)
    other = state.citizens.get(other_id)
    name = other.name if other is not None else other_id
    if relation is None:
        return m.RelationshipView(citizen_id=other_id, name=name, known=False)
    return m.RelationshipView(name=name, **relation.model_dump())


def relationships(state: m.WorldState, citizen_id: str) -> list[m.RelationshipView]:
    """Every tie this citizen holds toward a living citizen, by trust (highest first), then ID."""
    holder = state.citizens.get(citizen_id)
    if holder is None:
        raise KeyError("Unknown citizen")
    views = [
        _view(state, holder, r.citizen_id)
        for r in holder.relationships
        if r.citizen_id in state.citizens
    ]
    return sorted(views, key=lambda v: (-v.trust, v.citizen_id))


def strongest_ties(state: m.WorldState, citizen_id: str) -> list[m.RelationshipView]:
    """The few ties that matter most: largest |trust| or grudge, then citizen ID."""
    ties = [v for v in relationships(state, citizen_id) if v.trust or v.grudge]
    ties.sort(key=lambda v: (-max(abs(v.trust), v.grudge), v.citizen_id))
    return ties[:OBSERVED_TIES]


def relationship_pair(state: m.WorldState, a_id: str, b_id: str) -> m.RelationshipPair:
    """Both directions of a tie; a missing entry is reported neutral with known=false."""
    a, b = state.citizens.get(a_id), state.citizens.get(b_id)
    if a is None or b is None:
        raise KeyError("Unknown citizen")
    return m.RelationshipPair(
        a_id=a_id, b_id=b_id, a_to_b=_view(state, a, b_id), b_to_a=_view(state, b, a_id)
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
    """Businesses with at least one free slot, in building ID order.

    Only pending applications are listed; resolved (hired/rejected) records are kept as history.
    """
    applications = sorted(
        (a for a in state.job_applications.values() if a.status == "pending"),
        key=lambda a: a.sequence,
    )
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


def wealth(state: m.WorldState, citizen_id: str) -> int:
    """Own money plus the cash of every business the citizen owns."""
    citizen = state.citizens[citizen_id]
    return citizen.money + sum(b.cash for b in state.buildings.values() if b.owner_id == citizen_id)


def influence(state: m.WorldState, citizen_id: str) -> m.InfluenceBreakdown:
    """influence = 0.5 * wealth_share + 0.3 * reputation + 0.2 * avg_trust_from_others.

    Integer basis points (0-10000), floored, so votes are reproducible:
    - wealth_share: this citizen's wealth over all citizens' wealth (0 when nobody has any).
    - reputation: Citizen.reputation (0-100) * 100.
    - trust_from_others: mean over every other citizen of their trust in this one, mapped
      from -100..100 to 0..10000. A citizen with no relationship entry for this one counts
      as neutral trust 0 (5000), so someone nobody knows scores 5000; so does a lone citizen.
    """
    if citizen_id not in state.citizens:
        raise KeyError("Unknown citizen")
    total = sum(wealth(state, cid) for cid in state.citizens)
    own = wealth(state, citizen_id)
    wealth_share = own * 10000 // total if total else 0
    reputation = state.citizens[citizen_id].reputation * 100
    others = [c for cid, c in sorted(state.citizens.items()) if cid != citizen_id]
    trusts = [
        next((r.trust for r in c.relationships if r.citizen_id == citizen_id), 0) for c in others
    ]
    trust = sum((t + 100) * 50 for t in trusts) // len(trusts) if trusts else 5000
    return m.InfluenceBreakdown(
        citizen_id=citizen_id,
        wealth=own,
        wealth_share=wealth_share,
        reputation=reputation,
        trust_from_others=trust,
        influence=(5 * wealth_share + 3 * reputation + 2 * trust) // 10,
    )


def vote_tally(state: m.WorldState, vote: m.Vote) -> m.VoteTally:
    """Influence-weighted tally of ballots cast. Open votes use current influence;
    closed votes report the weights recorded when they closed. Abstentions carry no weight."""
    if vote.status == "open":
        yes = no = 0
        for cid, choice in sorted(vote.ballots.items()):
            if cid not in state.citizens:
                continue
            weight = influence(state, cid).influence
            yes, no = (yes + weight, no) if choice == "yes" else (yes, no + weight)
    else:
        yes, no = vote.yes_weight, vote.no_weight
    return m.VoteTally(
        yes_weight=yes,
        no_weight=no,
        yes_share=yes * 10000 // (yes + no) if yes + no else 0,
        ballots=len(vote.ballots),
    )


def votes(state: m.WorldState, status: str | None = None) -> list[m.VoteView]:
    return [
        m.VoteView(vote=vote.model_copy(deep=True), tally=vote_tally(state, vote))
        for _, vote in sorted(state.votes.items(), key=lambda item: (item[1].opens_tick, item[0]))
        if status is None or vote.status == status
    ]


# The permission matrix as data (agents-api.md section 2). Roles are derived:
# business_owner = owns at least one building. Lot ownership is separate from role.
_ANY = (
    "buy", "sell", "transfer_money", "consume", "communicate", "move_to", "adjust_goals",
    "construct_building", "found_business", "apply_job", "quit_job", "trade", "respond_trade",
    "lease_lot", "pay_rent", "interact", "research", "license_invention", "respond_license",
    "lend", "respond_loan", "repay", "propose_vote", "vote", "gather_resource",
)  # fmt: skip
_OWN_BUSINESS = (
    "set_price", "set_wage", "hire", "fire", "close_business", "adopt_invention", "produce",
    "upgrade_building", "reject_application",
)  # fmt: skip
_OWN_LOT = ("set_rent", "evict")
ROLE_DESCRIPTIONS = {
    "commoner": "Works, trades, rents, borrows, researches, and votes. Founding a business "
    "makes a commoner a business owner.",
    "business_owner": "Everything a commoner can do, plus running the businesses they own. "
    "Losing the last business makes them a commoner again.",
}


def roles() -> list[m.RoleInfo]:
    def perms(actions, scope):
        return [
            m.RolePermission(action=a, scope=scope, supported=a in SUPPORTED_ACTIONS)
            for a in actions
        ]

    common = perms(_ANY, "any") + perms(_OWN_LOT, "own_lot")
    return [
        m.RoleInfo(role="commoner", description=ROLE_DESCRIPTIONS["commoner"], permissions=common),
        m.RoleInfo(
            role="business_owner",
            description=ROLE_DESCRIPTIONS["business_owner"],
            permissions=common + perms(_OWN_BUSINESS, "own_business"),
        ),
    ]


def lot_profile(state: m.WorldState, plot_id: str) -> m.LotProfile:
    plot = state.plots.get(plot_id)
    if plot is None:
        raise KeyError("Unknown lot")
    building = next(
        (
            b.id
            for b in sorted(state.buildings.values(), key=lambda b: b.id)
            if b.plot_id == plot_id
        ),
        None,
    )
    use = "business" if building else "home" if plot.tenant_id else "empty"
    return m.LotProfile(lot=plot.model_copy(deep=True), use=use, building_id=building)
