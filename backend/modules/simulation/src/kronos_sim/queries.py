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
        influence=influence(state, citizen_id).influence,
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
    )


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
    "lease_lot", "pay_rent", "interact", "research", "license_invention", "lend", "repay",
    "propose_vote", "vote", "gather_resource",
)  # fmt: skip
_OWN_BUSINESS = (
    "set_price", "set_wage", "hire", "fire", "close_business", "adopt_invention", "produce",
    "upgrade_building",
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
