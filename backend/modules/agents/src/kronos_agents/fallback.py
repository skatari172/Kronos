"""Deterministic utility policy used when the AI provider fails (timeout, bad output, error).

Every candidate comes from the observation alone and from `available_actions`. Each one is
worth `value` points (0-100) to one or more goals; its utility is

    sum(goal_weights[goal] * value)  +  HUNGER_PRIORITY * max(0, hunger - HUNGER_URGENT)

where the hunger term applies to food actions only, so from hunger 70 eating or buying bread
beats anything a goal can score (at most 100 * 100). All arithmetic is integer, there is no
randomness, and the world RNG is never touched. Ties break by `ACTION_ORDER`, then by the
target ID. When no candidate applies, `choose` raises `ProviderError` rather than inventing
a no-op: the caller then skips this citizen's strategy, exactly like a failed provider call.
"""

import zlib
from dataclasses import dataclass, field

from kronos_sim.models import AgentAction, AgentObservation, ResourceInventory
from pydantic import TypeAdapter

from kronos_agents.provider import ProviderError

GOALS = ("wealth", "influence", "safety", "reputation")
HUNGER_URGENT = 50
HUNGER_PRIORITY = 600  # (70 - 50) * 600 > 100 * 100: hunger 70+ always eats first.
EAT_FROM = 20  # Eating below this hunger wastes bread.
WHEAT_VALUE = 100  # Cents per wheat when valuing trade offers (seed price).
DEFAULT_BREAD = 500  # Cents per bread when no bakery is observed.
POOR = 3000  # Below this, a citizen accepts loan offers (matches the `middle` tier floor).
# Stable tie-break: needs first, then obligations, then income, then social actions.
ACTION_ORDER = (
    "consume",
    "buy",
    "repay",
    "respond_loan",
    "respond_trade",
    "apply_job",
    "set_price",
    "set_wage",
    "interact",
    "communicate",
)
_ACTION = TypeAdapter(AgentAction)


@dataclass(frozen=True)
class Candidate:
    action: dict
    values: dict[str, int]  # goal -> 0..100
    reason: str
    food: bool = False
    target: str = ""
    utility: int = field(default=0, compare=False)


class UtilityPolicy:
    """Pick one action for the observed citizen by goal weights and hunger."""

    def choose(self, observation: AgentObservation) -> AgentAction:
        ranked = self.rank(observation)
        if not ranked:
            raise ProviderError("The fallback policy has no applicable action")
        best = ranked[0]
        weights = observation.citizen.goal_weights.model_dump()
        goal = (
            "hunger"
            if best.food and observation.citizen.hunger >= HUNGER_URGENT
            else max(GOALS, key=lambda g: (weights[g] * best.values.get(g, 0), -GOALS.index(g)))
        )
        rationale = f"{goal}: {best.reason}"[:280]
        return _ACTION.validate_python({**best.action, "rationale": rationale})

    def rank(self, observation: AgentObservation) -> list[Candidate]:
        """Every applicable candidate with its utility, best first."""
        weights = observation.citizen.goal_weights.model_dump()
        hunger = observation.citizen.hunger
        scored = []
        for c in self.candidates(observation):
            utility = sum(weights[g] * v for g, v in c.values.items())
            if c.food:
                utility += HUNGER_PRIORITY * max(0, hunger - HUNGER_URGENT)
            scored.append(
                Candidate(c.action, c.values, c.reason, c.food, c.target, utility=utility)
            )
        scored.sort(key=lambda c: (-c.utility, ACTION_ORDER.index(c.action["type"]), c.target))
        return scored

    def candidates(self, o: AgentObservation) -> list[Candidate]:
        allowed = set(o.available_actions)
        me = o.citizen
        actor = {"actor_id": me.id}
        out: list[Candidate] = []
        cheapest = min(o.bread_prices, key=lambda b: (o.bread_prices[b], b), default=None)
        bread_price = o.bread_prices[cheapest] if cheapest else DEFAULT_BREAD
        reserve = 2 * bread_price  # Never spend the last two loaves' worth on anything else.

        # Safety: eat what you have, or buy the cheapest bread you can afford.
        if "consume" in allowed and me.inventory.bread and me.hunger >= EAT_FROM:
            out.append(
                Candidate(
                    {**actor, "type": "consume"},
                    {"safety": me.hunger},
                    "I am hungry and have bread.",
                    food=True,
                )
            )
        if "buy" in allowed and cheapest and me.money >= bread_price and me.inventory.bread < 2:
            need = 40 + me.hunger // 2 if not me.inventory.bread else me.hunger // 3
            out.append(
                Candidate(
                    {
                        **actor,
                        "type": "buy",
                        "building_id": cheapest,
                        "resource": "bread",
                        "quantity": 1,
                        "max_unit_price": bread_price,
                    },
                    {"safety": min(100, need)},
                    "Bread is running low; this bakery is cheapest.",
                    food=True,
                    target=cheapest,
                )
            )

        # Reputation: pay debts down while keeping a food reserve.
        if "repay" in allowed:
            for loan in sorted(o.loans, key=lambda loan: loan.id):
                if loan.borrower_id != me.id or loan.status not in ("active", "defaulted"):
                    continue
                amount = min(loan.amount_owed - loan.amount_repaid, me.money - reserve)
                if amount <= 0:
                    continue
                urgent = loan.status == "defaulted" or loan.due_tick - o.tick <= 2
                out.append(
                    Candidate(
                        {**actor, "type": "repay", "loan_id": loan.id, "amount": amount},
                        {"reputation": 90 if urgent else 40, "safety": 10},
                        "Paying my debt keeps my name good.",
                        target=loan.id,
                    )
                )

        # Safety when poor: accept loan offers; otherwise politely decline them.
        if "respond_loan" in allowed:
            for loan in sorted(o.loans, key=lambda loan: loan.id):
                if loan.borrower_id != me.id or loan.status != "offered" or loan.due_tick <= o.tick:
                    continue
                accept = me.money < POOR
                out.append(
                    Candidate(
                        {**actor, "type": "respond_loan", "loan_id": loan.id, "accept": accept},
                        {"safety": 50} if accept else {"safety": 10},
                        "I need the money to get by."
                        if accept
                        else "I have enough; I would rather not owe anyone.",
                        target=loan.id,
                    )
                )

        # Wealth: accept trade offers that gain value and that I can pay; decline the rest.
        if "respond_trade" in allowed:
            for offer in sorted(o.incoming_offers, key=lambda offer: offer.id):
                if offer.recipient_id != me.id:
                    continue
                gain = _worth(offer.give.money, offer.give.goods, bread_price) - _worth(
                    offer.get.money, offer.get.goods, bread_price
                )
                can_pay = me.money >= offer.get.money and _holds(me.inventory, offer.get.goods)
                accept = gain > 0 and can_pay
                out.append(
                    Candidate(
                        {**actor, "type": "respond_trade", "offer_id": offer.id, "accept": accept},
                        {"wealth": min(100, 20 + gain // 50)} if accept else {"wealth": 10},
                        f"The trade gains me {gain} cents of value."
                        if accept
                        else "The trade does not pay off for me.",
                        target=offer.id,
                    )
                )

        # Wealth: the unemployed apply to the best-paying opening they have not applied to.
        if "apply_job" in allowed and me.employer_id is None:
            jobs = [
                j
                for j in o.open_jobs
                if j.free_slots > 0 and me.id not in j.applicant_ids and j.owner_id != me.id
            ]
            if jobs:
                job = min(jobs, key=lambda j: (-j.wage, j.building_id))
                need = {"poor": 80, "middle": 60}.get(o.wealth_tier, 30)
                out.append(
                    Candidate(
                        {**actor, "type": "apply_job", "building_id": job.building_id},
                        {"wealth": need, "safety": 20},
                        f"A steady wage of {job.wage} cents a day at {job.name}.",
                        target=job.building_id,
                    )
                )

        # Wealth for owners: move the bread price with stock; cut wages that cash cannot cover.
        for business in o.businesses:
            b = business.building
            price = b.prices.get("bread")
            if "set_price" in allowed and b.kind == "bakery" and price:
                new = None
                if b.inventory.bread >= 20:
                    new = max(100, price * 9 // 10)
                elif b.inventory.bread < 3:
                    new = min(2000, price * 11 // 10)
                if new and new != price:
                    out.append(
                        Candidate(
                            {
                                **actor,
                                "type": "set_price",
                                "building_id": b.id,
                                "resource": "bread",
                                "price": new,
                            },
                            {"wealth": 40},
                            "Bread is piling up; a lower price will sell it."
                            if new < price
                            else "Bread is scarce; it can fetch more.",
                            target=b.id,
                        )
                    )
            payroll = b.wage * len(business.employee_ids)
            if "set_wage" in allowed and payroll and b.cash < 3 * payroll and b.wage > 100:
                out.append(
                    Candidate(
                        {
                            **actor,
                            "type": "set_wage",
                            "building_id": b.id,
                            "wage": max(100, b.wage * 9 // 10),
                        },
                        {"wealth": 50, "safety": 20},
                        "Cash covers under three days of wages; trim pay to stay open.",
                        target=b.id,
                    )
                )

        # Influence and reputation: befriend someone, or share news with a neighbor.
        neighbors = sorted(o.neighbors)
        ties = {t.citizen_id: t for t in o.ties}
        starving = me.hunger >= HUNGER_URGENT and me.money < bread_price and not me.inventory.bread
        # Who I reached out to lately: befriending raises *their* trust, not mine, so my
        # own ties never show it; without this, everyone befriends the same person daily.
        lately = {
            e.payload.recipient_id
            for e in o.recent_events
            if e.type == "citizen_interacted" and e.actor_id == me.id
        }
        if neighbors and "interact" in allowed:
            fresh = [
                n
                for n in neighbors
                if n not in lately
                and (
                    n not in ties
                    or (ties[n].last_interaction_tick != o.tick and ties[n].grudge < 50)
                )
            ]
            if fresh:
                # Spread warmth: the least-close neighbors first, rotating day by day.
                target = min(
                    fresh,
                    key=lambda n: (
                        ties[n].trust if n in ties else 0,
                        (zlib.crc32(f"{me.id}:{n}".encode()) + o.tick) % 97,
                    ),
                )
                close = ties[target].trust if target in ties else 0
                # Making friends matters far less to someone starving.
                weight = 4 if starving else 1
                out.append(
                    Candidate(
                        {**actor, "type": "interact", "recipient_id": target, "kind": "befriend"},
                        {
                            "influence": max(10, 40 - max(0, close) // 3) // weight,
                            "reputation": 15 // weight,
                        },
                        f"Friends make my word count; I will befriend {o.neighbors[target]}.",
                        target=target,
                    )
                )
        # Starving and broke: ask a neighbor (a friend if I have one) for a loan.
        if starving and neighbors and "communicate" in allowed:
            helper = max(
                neighbors,
                key=lambda n: (ties[n].trust if n in ties else 0, -neighbors.index(n)),
            )
            short = bread_price - me.money
            message = (
                f"I'm starving with {me.money} cents and bread costs {bread_price}. "
                f"Could you lend me {short} cents? I'll repay you from my wages."
            )
            out.append(
                Candidate(
                    {**actor, "type": "communicate", "recipient_id": helper, "message": message},
                    {"safety": 60 + me.hunger // 2},
                    f"I can't afford bread; {o.neighbors[helper]} might lend me enough to eat.",
                    target=helper,
                )
            )
        if neighbors and "communicate" in allowed:
            target = neighbors[0]
            message = (
                f"Bread costs {bread_price} cents at the cheapest bakery."
                if cheapest
                else "Has anyone seen fresh bread today?"
            )
            out.append(
                Candidate(
                    {**actor, "type": "communicate", "recipient_id": target, "message": message},
                    {"reputation": 25, "influence": 10},
                    "Sharing news keeps me in good standing.",
                    target=target,
                )
            )
        return out


def _worth(money: int, goods: ResourceInventory, bread_price: int) -> int:
    return money + goods.bread * bread_price + goods.wheat * WHEAT_VALUE


def _holds(inventory: ResourceInventory, goods: ResourceInventory) -> bool:
    return inventory.bread >= goods.bread and inventory.wheat >= goods.wheat
