"""Copy-on-write transactions. Only the engine changes live world values."""

import json
import random
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import get_args

from pydantic import TypeAdapter

from kronos_sim import models as m

EVENT = TypeAdapter(m.SimulationEvent)
ACTION = TypeAdapter(m.AgentAction)
# Action types with engine rules; every other AgentAction is rejected as not_supported.
# Every player intervention command; queued ones run before citizen actions on a tick.
INTERVENTIONS = get_args(get_args(m.Intervention)[0])

SUPPORTED_ACTIONS = (
    "buy",
    "sell",
    "transfer_money",
    "set_price",
    "produce",
    "consume",
    "communicate",
    "construct_building",
    "upgrade_building",
    "move_to",
    "adjust_goals",
    "found_business",
    "close_business",
    "set_wage",
    "hire",
    "fire",
    "gather_resource",
    "apply_job",
    "quit_job",
    "reject_application",
    "lend",
    "respond_loan",
    "repay",
    "trade",
    "respond_trade",
    "research",
    "license_invention",
    "respond_license",
    "adopt_invention",
    "propose_vote",
    "vote",
    "lease_lot",
    "set_rent",
    "pay_rent",
    "evict",
    "interact",
)
MIN_CAPITAL = 5000  # Cents a founder must move into a new business.
BANKRUPTCY_DAYS = 3  # Consecutive days with a missed wage before a business closes.
# Which business kind may draw on each natural stock (farm harvests and worker gathering).
RESOURCE_SOURCES: dict[str, m.BuildingKind] = {"wheat": "farm"}
DEFAULT_TRUST_PENALTY = 30  # Lender trust lost toward a defaulting borrower (spec grudge +0.3).
DEFAULT_REPUTATION_PENALTY = 5  # Borrower reputation lost on default (spec -0.05 on 0..1).
DEFAULT_GRUDGE = 30  # Lender grudge gained toward a defaulting borrower (spec +0.3).
OFFER_TTL_DAYS = 2  # An offer made on tick t may be accepted through tick t + 2.
MAX_PENDING_OFFERS = 5  # Outgoing pending offers per citizen.
VOTE_DAYS = 3  # A town vote closes this many days after it opens.
VOTE_CADENCE_DAYS = 10  # Spec "every 10 ticks one proposal goes to a vote": min gap between opens.
RENT_PERIOD_DAYS = 7  # Rent is collected on every tick divisible by this.
MAX_RENT_CHANGE_PERCENT = 20  # Per set_rent while a lot is leased.
MIN_RENT_STEP = 100  # Cents; lets a leased lot at zero (or tiny) rent still change.
EVICTION_PERIODS = 3  # Missed rent periods before the owner may evict.
MAX_PREPAID_PERIODS = 4  # How far ahead a tenant may pay.
# Village growth (Engine._grow, a daily step with no AI). Money is cents; 1 coin = 100 cents.
NEW_PLOTS_PER_EXPANSION = 2  # Town-land lots opened once every lot is built on or leased.
PLOT_SPACING_X = 4  # Seed lots sit at x in {-4, 0, 4} ...
PLOT_SPACING_Z = 6  # ... and z in {-3, 3}; new lots continue that grid ring by ring.
NEWCOMER_INTERVAL_DAYS = 3  # A newcomer may arrive on ticks divisible by this.
NEWCOMER_MAX_AVG_HUNGER = 50  # Only a village whose average hunger is below this attracts one.
NEWCOMER_MONEY = 1000  # 10 coins.
NEWCOMER_NAMES = (
    "Ivo",
    "Lena",
    "Bram",
    "Clara",
    "Otto",
    "Nell",
    "Silas",
    "Wren",
    "Hugo",
    "Talia",
    "Jonas",
    "Edda",
)
LEAVE_AFTER_DAYS = 3  # Days in a row at hunger 100 with no money before a citizen leaves.
FOUNDER_MIN_MONEY = 8000  # A saver founds a business holding more than 80 coins ...
FOUNDER_CAPITAL = 5000  # ... and puts 50 coins in as business cash.
FOUNDING_ORDER: tuple[m.BuildingKind, ...] = ("farm", "bakery", "market")  # Tie order.
UPGRADE_MIN_CASH = 10000  # A full business holding more than 100 coins upgrades ...
UPGRADE_COST = 2500  # ... paying 25 coins from its cash (spent, as with upgrade_building) ...
UPGRADE_JOB_SLOTS = 2  # ... for this many extra job slots.
MAX_LEVEL = 3
RENTER_MIN_MONEY = 2000  # An employed citizen with more than 20 coins rents a free home.
BUSINESS_CASH_CAP = 20000  # 200 coins; surplus is paid out to staff each day (tuned: 120-day run).
# interact effects (spec section 5.2, 0..1 values scaled by 100): (trust delta, grudge delta).
# Each applies to the target's feeling toward the actor; MUTUAL_INTERACTIONS also change the
# actor's feeling toward the target the same way.
INTERACTIONS: dict[str, tuple[int, int]] = {
    "befriend": (10, 0),
    "gift": (15, -5),
    "ally": (20, 0),
    "argue": (-10, 10),
    "insult": (-15, 20),
    "betray": (-50, 50),
    "mentor": (10, 0),
}
MUTUAL_INTERACTIONS = ("ally", "argue")
ALLY_MIN_TRUST = 50  # Target's trust toward the actor needed to form an alliance.
FRIEND_TRUST = 50  # befriend turns an acquaintance into a friend at this trust.
INSULT_REPUTATION = 2  # Target reputation lost to an insult.
BETRAY_REPUTATION = 10  # Actor reputation lost by betraying.
MENTOR_REPUTATION = 2  # Mentee reputation gained (stands in for skill until one exists).
INTERACTION_VERBS = {
    "befriend": "befriended",
    "gift": "gave a gift to",
    "ally": "allied with",
    "argue": "argued with",
    "insult": "insulted",
    "betray": "betrayed",
    "mentor": "mentored",
}


class InvalidAction(ValueError):
    """A rule rejection with a stable code for agents and a message for people."""

    def __init__(self, code: m.ActionErrorCode, message: str):
        super().__init__(message)
        self.code = code


def _policy(policies: m.Policies, kind: str) -> int:
    return policies.market_tax_bps if kind == "market_tax" else getattr(policies, kind)


def _tuples(value):
    return tuple(_tuples(v) for v in value) if isinstance(value, list) else value


def _lot_payload(plot: m.Plot) -> dict:
    return dict(
        plot_id=plot.id,
        owner_id=plot.owner_id,
        tenant_id=plot.tenant_id,
        rent=plot.rent,
        arrears=plot.arrears,
        missed_periods=plot.missed_periods,
        prepaid_periods=plot.prepaid_periods,
    )


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _tie(holder: m.Citizen, other_id: str) -> m.Relationship:
    """holder's relationship entry toward other_id, created neutral on first contact."""
    relation = next((r for r in holder.relationships if r.citizen_id == other_id), None)
    if relation is None:
        relation = m.Relationship(citizen_id=other_id)
        holder.relationships.append(relation)
    return relation


def _tie_payload(holder: m.Citizen, relation: m.Relationship) -> dict:
    """relationship_changed payload: holder's feeling toward relation.citizen_id."""
    return dict(
        recipient_id=holder.id,
        trust=relation.trust,
        grudge=relation.grudge,
        type=relation.type,
        citizen_id=relation.citizen_id,
    )


def _check_build_rights(plot: m.Plot, citizen_id: str):
    """Town land is open to anyone; a private lot needs its owner or tenant."""
    if plot.owner_id is not None and citizen_id not in (plot.owner_id, plot.tenant_id):
        raise InvalidAction("not_owner", "This lot belongs to someone else; lease it first")


# Memories (Engine._remember, applied to every emitted event; no AI, no RNG).
MEMORY_WINDOW = 8  # Recent first-person lines kept verbatim on each citizen.
SUMMARY_MAX = 400  # Characters; Citizen.memory_summary is bounded.
_REPEAT = re.compile(r"(.*) \(x(\d+)\)")
_MESSAGE = re.compile(r"[^:]{1,60}: .*")


def _plural(count: int, word: str) -> str:
    return f"{count:,} {word}{'' if count == 1 else 's'}"


def _render_summary(t: dict[str, int]) -> str:
    """Deterministic one-line digest of a citizen's memory tally."""
    parts = []
    if t.get("wage_days"):
        days = _plural(t["wage_days"], "day")
        parts.append(f"earned {t.get('wage_cents', 0):,} cents in wages over {days}")
    if t.get("payout_cents"):
        parts.append(f"received {t['payout_cents']:,} cents in business payouts")
    if t.get("purchases"):
        parts.append(
            f"bought goods {_plural(t['purchases'], 'time')} for {t.get('spent_cents', 0):,} cents"
        )
    if t.get("meals"):
        parts.append(f"ate {_plural(t['meals'], 'time')}")
    if t.get("tax_cents"):
        parts.append(f"received {t['tax_cents']:,} cents in market tax shares")
    if t.get("rejections"):
        parts.append(_plural(t["rejections"], "rejected action"))
    if t.get("messages"):
        parts.append(_plural(t["messages"], "message"))
    if t.get("notes"):
        parts.append(_plural(t["notes"], "older event"))
    text = "Earlier: " + "; ".join(parts) if parts else ""
    return text if len(text) <= SUMMARY_MAX else text[: SUMMARY_MAX - 3] + "..."


def tally(citizen: m.Citizen, **counts: int):
    """Add routine counts (wages, meals, purchases, folded lines) to the rolling summary."""
    for key, value in counts.items():
        citizen.memory_tally[key] = citizen.memory_tally.get(key, 0) + value
    citizen.memory_summary = _render_summary(citizen.memory_tally)


def remember(citizen: m.Citizen, line: str):
    """Append one memory line. A repeat of the latest line becomes "line (xN)"; lines beyond
    MEMORY_WINDOW fold, oldest first, into the counts behind memory_summary."""
    if citizen.memories:
        repeat = _REPEAT.fullmatch(citizen.memories[-1])
        last, count = (repeat[1], int(repeat[2])) if repeat else (citizen.memories[-1], 1)
        if last == line:
            citizen.memories[-1] = f"{line} (x{count + 1})"
            return
    citizen.memories.append(line)
    while len(citizen.memories) > MEMORY_WINDOW:
        oldest = citizen.memories.pop(0)
        repeat = _REPEAT.fullmatch(oldest)
        text, count = (repeat[1], int(repeat[2])) if repeat else (oldest, 1)
        if text.startswith("Rejected "):
            tally(citizen, rejections=count)
        elif _MESSAGE.fullmatch(text):
            tally(citizen, messages=count)
        else:
            tally(citizen, notes=count)


class Engine:
    def __init__(self, state: m.WorldState):
        self.state = state.model_copy(deep=True)
        self.events: list[m.SimulationEvent] = []
        self.rng = random.Random()
        self.rng.setstate(_tuples(state.rng_state))
        self.action_id: str | None = None

    def emit(self, kind: str, payload: dict, actor_id=None, rationale=None, causal_refs=None):
        self.state.sequence += 1
        event = EVENT.validate_python(
            dict(
                id=f"{self.state.branch_id}:{self.state.sequence}",
                branch_id=self.state.branch_id,
                tick=self.state.tick,
                sequence=self.state.sequence,
                type=kind,
                payload=payload,
                actor_id=actor_id,
                rationale=rationale,
                causal_refs=causal_refs or [],
                action_id=self.action_id,
            )
        )
        self.events.append(event)
        self._remember(kind, payload, actor_id)
        return event

    def _name(self, entity_id: str | None) -> str:
        s = self.state
        entity = s.citizens.get(entity_id) or s.buildings.get(entity_id)
        return entity.name if entity is not None else str(entity_id)

    def _remember(self, kind: str, p: dict, actor_id: str | None):
        """Turn one event into first-person memories for the citizens it involves.

        Salient events become lines (Engine `remember`); routine ones (wages, meals, everyday
        purchases, tax shares) only add to the rolling summary counts. Rejections are written
        by `reject`, so action_rejected is skipped here. Deterministic; never touches the RNG.
        """
        s = self.state
        citizen = s.citizens.get
        name = self._name

        def note(cid, line):
            if citizen(cid) is not None:
                remember(citizen(cid), line)

        def staff_and_owner(building_id):
            """The business's owner and its staff other than the actor (who already knows)."""
            building = s.buildings.get(building_id)
            staff = sorted(
                c.id
                for c in s.citizens.values()
                if c.employer_id == building_id and c.id != actor_id
            )
            return (building.owner_id if building else None), staff

        if kind == "transaction_completed":
            sender, recipient, amount = p["sender_id"], p["recipient_id"], p["amount"]
            if p.get("resource"):
                if citizen(sender) and sender != actor_id:
                    return  # Goods handed over in a trade; trade events cover it.
                if citizen(sender) and recipient in s.buildings:
                    tally(citizen(sender), purchases=1, spent_cents=amount)
                elif sender in s.buildings and citizen(recipient) and amount:
                    resource = p["resource"]
                    note(
                        recipient,
                        f"Sold {p['quantity']} {resource} to {name(sender)} for {amount:,} cents",
                    )
            elif sender in s.buildings and citizen(recipient):
                wage = citizen(recipient).employer_id == sender and actor_id == recipient
                if wage:
                    tally(citizen(recipient), wage_cents=amount, wage_days=1)
                else:
                    tally(citizen(recipient), payout_cents=amount)
            elif sender == "town" and citizen(recipient):
                note(recipient, f"The town gave me {amount:,} cents")
            elif recipient == "town" and citizen(sender):
                note(sender, f"The town took {amount:,} cents from me")
        elif kind == "resource_consumed" and p["resource"] == "bread" and citizen(p["entity_id"]):
            tally(citizen(p["entity_id"]), meals=p["quantity"])
        elif kind == "tax_collected":
            for cid in p["recipient_ids"]:
                if citizen(cid):
                    tally(citizen(cid), tax_cents=p["per_citizen"])
        elif kind == "price_changed":
            owner, staff = staff_and_owner(p["building_id"])
            line = (
                f"{p['resource'].capitalize()} at {name(p['building_id'])} went from "
                f"{p['old_price']:,} to {p['new_price']:,} cents"
            )
            for cid in staff + ([owner] if owner not in (actor_id, *staff) else []):
                note(cid, line)
        elif kind == "wage_changed":
            owner, staff = staff_and_owner(p["building_id"])
            for cid in staff:
                note(
                    cid,
                    f"My wage at {name(p['building_id'])} went from "
                    f"{p['old_wage']:,} to {p['new_wage']:,} cents",
                )
            if owner not in (actor_id, *staff):
                note(
                    owner, f"Wages at {name(p['building_id'])} were set to {p['new_wage']:,} cents"
                )
        elif kind == "employment_changed" and p["building_id"] is None:
            previous = name(p.get("previous_building_id"))
            worker = p["citizen_id"]
            note(
                worker,
                f"I quit my job at {previous}"
                if actor_id == worker
                else f"I lost my job at {previous}",
            )
        elif kind == "job_application_resolved":
            building = name(p["building_id"])
            if p["outcome"] == "accepted":
                note(p["citizen_id"], f"Hired by {building}")
            elif p["outcome"] == "rejected":
                note(p["citizen_id"], f"{building} rejected my application")
        elif kind == "agent_spoke":
            note(actor_id, f"To {name(p['recipient_id'])}: {p['message']}")
            note(p["recipient_id"], f"{name(actor_id)}: {p['message']}")
        elif kind == "citizen_interacted":
            verb = INTERACTION_VERBS[p["kind"]]
            note(actor_id, f"I {verb} {name(p['recipient_id'])}")
            note(p["recipient_id"], f"{name(actor_id)} {verb} me")
        elif kind == "license_offered":
            invention = s.inventions.get(p["invention_id"])
            note(
                p["recipient_id"],
                f"{name(p['owner_id'])} offers a "
                f"{invention.name if invention else p['invention_id']} license for {p['fee']} "
                f"({p['offer_id']})",
            )
        elif kind == "license_resolved" and p.get("status") in ("accepted", "declined"):
            note(p["owner_id"], f"{name(p['recipient_id'])} {p['status']} my license offer")
        elif kind == "trade_offered":
            note(p["recipient_id"], f"{name(p['sender_id'])} offered me a trade ({p['offer_id']})")
        elif kind in ("trade_accepted", "trade_declined", "trade_expired"):
            verb = kind.removeprefix("trade_")
            note(p["sender_id"], f"Trade {p['offer_id']} with {name(p['recipient_id'])} {verb}")
        elif kind == "loan_offered":
            note(
                p["borrower_id"],
                f"{name(p['lender_id'])} offered me a {p['principal']:,}-cent loan "
                f"({p['loan_id']})",
            )
        elif kind in ("loan_accepted", "loan_declined"):
            verb = kind.removeprefix("loan_")
            note(p["lender_id"], f"{name(p['borrower_id'])} {verb} my loan {p['loan_id']}")
        elif kind == "loan_repaid":
            note(p["lender_id"], f"{name(p['borrower_id'])} repaid me {p['amount']:,} cents")
        elif kind == "loan_defaulted":
            note(
                p["borrower_id"], f"I defaulted on loan {p['loan_id']} from {name(p['lender_id'])}"
            )
            note(p["lender_id"], f"{name(p['borrower_id'])} defaulted on my loan {p['loan_id']}")
        elif kind == "rent_missed":
            note(p["tenant_id"], f"I missed rent on {p['plot_id']}; I owe {p['arrears']:,} cents")
        elif kind == "tenant_evicted" and actor_id != p["tenant_id"]:
            note(p["tenant_id"], f"I was evicted from {p['plot_id']}")
            if actor_id == p["owner_id"]:
                note(p["owner_id"], f"I evicted {name(p['tenant_id'])} from {p['plot_id']}")
        elif kind == "lot_leased" and actor_id != p["owner_id"]:
            note(p["owner_id"], f"{name(p['tenant_id'])} leased my lot {p['plot_id']}")
        elif kind == "building_constructed" and actor_id is not None:
            note(actor_id, f"I opened {name(p['entity_id'])}")
        elif kind == "policy_changed":
            for cid in sorted(s.citizens):
                note(cid, f"Town policy {p['kind']} is now {p['new_value']:,}")
        elif kind == "citizen_spawned":
            newcomer = p["entity_id"]
            for cid in sorted(s.citizens):
                note(
                    cid,
                    "I arrived in the village"
                    if cid == newcomer
                    else f"{name(newcomer)} arrived in the village",
                )
        elif kind == "intervention_applied" and p.get("kind") == "adjust_hunger":
            change = p["command"]["change"]
            line = "A famine made me hungrier" if change > 0 else "A feast eased my hunger"
            for cid in p.get("affected_ids", []):
                note(cid, line)

    def result(self, rejected=None) -> m.SimulationTickResult:
        self.state.rng_state = json.loads(json.dumps(self.rng.getstate()))
        occupied = [building.plot_id for building in self.state.buildings.values()]
        if len(occupied) != len(set(occupied)):
            raise ValueError("Multiple buildings occupy one plot")
        if any(self._free_slots(building) < 0 for building in self.state.buildings.values()):
            raise ValueError("Business exceeds its job capacity")
        # Revalidate every committed state, including mutated nested models.
        state = m.WorldState.model_validate(self.state.model_dump())
        return m.SimulationTickResult(
            branch_id=state.branch_id,
            tick=state.tick,
            sequence=state.sequence,
            state=state,
            events=self.events,
            rejected_actions=rejected or [],
        )

    def apply(self, action: m.AgentAction, action_id: str | None = None) -> m.SimulationTickResult:
        transaction = Engine(self.state)
        transaction.action_id = action_id
        transaction._execute(ACTION.validate_python(action.model_dump()))
        return transaction.result()

    def reject(
        self, action: m.AgentAction, error: InvalidAction, action_id: str | None = None
    ) -> m.SimulationTickResult:
        """Record refusal without changing citizen, economic, or random state."""
        tx = Engine(self.state)
        tx.action_id = action_id
        actor = tx.state.citizens.get(action.actor_id)
        # A queued action can outlive its citizen (they left town); the refusal is still
        # logged so the queue resolves, but there is nobody to remember it.
        if actor is not None:
            remember(actor, f"Rejected {action.type}: {error}")
        tx.emit(
            "action_rejected",
            dict(action_type=action.type, code=error.code, message=str(error)),
            action.actor_id if actor is not None else None,
            action.rationale,
        )
        return tx.result()

    def _execute(self, action: m.AgentAction):
        s = self.state
        if action.actor_id not in s.citizens:
            raise InvalidAction("unknown_entity", "Unknown citizen")
        actor = s.citizens[action.actor_id]
        building = None
        if isinstance(action, m.GatherResource) and actor.employer_id != action.building_id:
            raise InvalidAction("bad_params", "Gathering requires a job at that business")
        if hasattr(action, "building_id"):
            building = s.buildings.get(action.building_id)
            if building is None:
                raise InvalidAction("unknown_entity", "Unknown building")
        owner_only = (
            m.SetPrice,
            m.Produce,
            m.UpgradeBuilding,
            m.CloseBusiness,
            m.SetWage,
            m.Hire,
            m.Fire,
            m.RejectApplication,
            m.AdoptInvention,
        )
        if isinstance(action, owner_only):
            if building.owner_id != actor.id:
                raise InvalidAction("not_owner", "Only the owner may perform this action")

        def emit(kind, payload):
            return self.emit(kind, payload, actor.id, action.rationale)

        plot = None
        if isinstance(action, (m.LeaseLot, m.SetRent, m.PayRent, m.Evict)):
            plot = s.plots.get(action.plot_id)
            if plot is None:
                raise InvalidAction("unknown_entity", "Unknown lot")
            if isinstance(action, (m.SetRent, m.Evict)) and plot.owner_id != actor.id:
                raise InvalidAction("not_owner", "Only the lot owner may perform this action")

        if isinstance(action, (m.Buy, m.Sell)):
            price = building.prices.get(action.resource)
            if price is None:
                raise InvalidAction("bad_params", "Resource is not traded here")
            buying = isinstance(action, m.Buy)
            if buying and price > action.max_unit_price:
                raise InvalidAction("bad_params", "Price exceeds buyer limit")
            source, target = (building, actor) if buying else (actor, building)
            amount = action.quantity * price
            balance = actor.money if buying else building.cash
            if getattr(source.inventory, action.resource) < action.quantity:
                raise InvalidAction("out_of_stock", "Not enough stock")
            if balance < amount:
                raise InvalidAction("insufficient_funds", "Insufficient funds")
            setattr(
                source.inventory,
                action.resource,
                getattr(source.inventory, action.resource) - action.quantity,
            )
            setattr(
                target.inventory,
                action.resource,
                getattr(target.inventory, action.resource) + action.quantity,
            )
            actor.money += -amount if buying else amount
            building.cash += amount if buying else -amount
            emit(
                "transaction_completed",
                dict(
                    sender_id=actor.id if buying else building.id,
                    recipient_id=building.id if buying else actor.id,
                    amount=amount,
                    resource=action.resource,
                    quantity=action.quantity,
                ),
            )
            if buying:
                self._collect_tax(building, amount, actor.id, action.rationale)
        elif isinstance(action, m.TransferMoney):
            recipient = s.citizens.get(action.recipient_id)
            if recipient is None or recipient.id == actor.id:
                raise InvalidAction("bad_params", "Invalid recipient")
            if actor.money < action.amount:
                raise InvalidAction("insufficient_funds", "Insufficient funds")
            actor.money -= action.amount
            recipient.money += action.amount
            emit(
                "transaction_completed",
                dict(sender_id=actor.id, recipient_id=recipient.id, amount=action.amount),
            )
        elif isinstance(action, m.SetPrice):
            cap = s.policies.bread_price_cap
            if action.resource == "bread" and cap and action.price > cap:
                raise InvalidAction("bad_params", f"The town caps bread at {cap} cents")
            old = building.prices[action.resource]
            building.prices[action.resource] = action.price
            emit(
                "price_changed",
                dict(
                    building_id=building.id,
                    resource=action.resource,
                    old_price=old,
                    new_price=action.price,
                ),
            )
        elif isinstance(action, m.Produce):
            if building.kind == "farm":
                # The seeded roll is the attempted harvest; the shared field limits it.
                resource, attempted = "wheat", self.rng.randint(3, 6) * building.level
                field = self._stock(resource)
                quantity = min(attempted, field.stock)
                field.stock -= quantity
            elif building.kind == "bakery":
                if building.inventory.wheat < 2:
                    raise InvalidAction("out_of_stock", "Bakery requires two wheat")
                building.inventory.wheat -= 2
                emit("resource_consumed", dict(entity_id=building.id, resource="wheat", quantity=2))
                resource, quantity = "bread", 3 * building.level
            else:
                raise InvalidAction("bad_params", "Markets do not produce goods")
            quantity = self._boosted(building, resource, quantity)
            setattr(building.inventory, resource, getattr(building.inventory, resource) + quantity)
            payload = dict(entity_id=building.id, resource=resource, quantity=quantity)
            if building.kind == "farm":
                payload["stock_remaining"] = field.stock
            emit("resource_produced", payload)
        elif isinstance(action, m.Consume):
            if actor.inventory.bread < 1:
                raise InvalidAction("out_of_stock", "No bread to consume")
            actor.inventory.bread -= 1
            actor.hunger = max(0, actor.hunger - 30)
            emit("resource_consumed", dict(entity_id=actor.id, resource="bread", quantity=1))
        elif isinstance(action, m.MoveTo):
            plot = s.plots.get(action.plot_id)
            if plot is None:
                raise InvalidAction("unknown_entity", "Unknown waypoint")
            actor.position = m.Position(x=plot.position.x, z=0)
            emit("citizen_moved", dict(entity_id=actor.id, position=actor.position.model_dump()))
        elif isinstance(action, m.Communicate):
            recipient = s.citizens.get(action.recipient_id)
            if recipient is None or recipient.id == actor.id:
                raise InvalidAction("bad_params", "Unknown or self recipient")
            emit("agent_spoke", dict(recipient_id=recipient.id, message=action.message))
            relation = _tie(recipient, actor.id)
            relation.trust = min(100, relation.trust + 1)
            emit("relationship_changed", _tie_payload(recipient, relation))
        elif isinstance(action, m.ConstructBuilding):
            plot = s.plots.get(action.plot_id)
            if plot is None:
                raise InvalidAction("unknown_entity", "Unknown plot")
            if any(b.plot_id == action.plot_id for b in s.buildings.values()):
                raise InvalidAction("lot_occupied", "Construction needs a vacant plot")
            _check_build_rights(plot, actor.id)
            if actor.money < 5000:
                raise InvalidAction("insufficient_funds", "Construction costs 50 coins")
            actor.money -= 5000
            bid = f"building-{s.branch_id}-{s.sequence + 1}"
            s.buildings[bid] = m.Building(
                id=bid,
                name=f"{actor.name}'s {action.kind}",
                kind=action.kind,
                plot_id=plot.id,
                position=plot.position.model_copy(),
                owner_id=actor.id,
                cash=0,
                wage=max(150, s.policies.min_wage),
                prices={"bread": min(500, s.policies.bread_price_cap or 500), "wheat": 100},
            )
            emit("building_constructed", dict(entity_id=bid, position=plot.position.model_dump()))
        elif isinstance(action, m.UpgradeBuilding):
            self._upgrade(building, action.rationale)
        elif isinstance(action, m.FoundBusiness):
            plot = s.plots.get(action.plot_id)
            if plot is None:
                raise InvalidAction("unknown_entity", "Unknown plot")
            if any(b.plot_id == plot.id for b in s.buildings.values()):
                raise InvalidAction("lot_occupied", "A business needs a vacant plot")
            _check_build_rights(plot, actor.id)
            if action.capital < MIN_CAPITAL:
                raise InvalidAction("bad_params", f"Capital must be at least {MIN_CAPITAL} cents")
            if actor.money < action.capital:
                raise InvalidAction("insufficient_funds", "Insufficient funds for that capital")
            actor.money -= action.capital
            bid = f"building-{s.branch_id}-{s.sequence + 1}"
            s.buildings[bid] = m.Building(
                id=bid,
                name=f"{actor.name}'s {action.kind}",
                kind=action.kind,
                plot_id=plot.id,
                position=plot.position.model_copy(),
                owner_id=actor.id,
                cash=action.capital,
                wage=max(150, s.policies.min_wage),
                prices={"bread": min(500, s.policies.bread_price_cap or 500), "wheat": 100},
            )
            emit("building_constructed", dict(entity_id=bid, position=plot.position.model_dump()))
            emit(
                "transaction_completed",
                dict(sender_id=actor.id, recipient_id=bid, amount=action.capital),
            )
        elif isinstance(action, m.CloseBusiness):
            self._close(building, actor.id, action.rationale)
        elif isinstance(action, m.SetWage):
            if action.wage < s.policies.min_wage:
                raise InvalidAction(
                    "bad_params", f"The town minimum wage is {s.policies.min_wage} cents"
                )
            old = building.wage
            building.wage = action.wage
            emit(
                "wage_changed",
                dict(building_id=building.id, old_wage=old, new_wage=action.wage),
            )
        elif isinstance(action, m.Hire):
            worker = s.citizens.get(action.citizen_id)
            if worker is None:
                raise InvalidAction("unknown_entity", "Unknown citizen")
            if worker.employer_id in s.buildings:
                raise InvalidAction("already_employed", f"{worker.name} already has a job")
            application = self._application(worker.id, building.id)
            if application is None:
                raise InvalidAction("bad_params", f"{worker.name} has not applied here")
            if self._free_slots(building) < 1:
                raise InvalidAction("no_free_slot", "No free job slot")
            self._hire(application, actor.id, action.rationale)
        elif isinstance(action, m.Fire):
            worker = s.citizens.get(action.citizen_id)
            if worker is None:
                raise InvalidAction("unknown_entity", "Unknown citizen")
            if worker.employer_id != building.id:
                raise InvalidAction("bad_params", f"{worker.name} does not work here")
            worker.employer_id = None
            emit(
                "employment_changed",
                dict(citizen_id=worker.id, building_id=None, previous_building_id=building.id),
            )
        elif isinstance(action, m.AdjustGoals):
            old = actor.goal_weights
            raw = {
                goal: min(100, max(0, getattr(old, goal) + getattr(action.changes, goal)))
                for goal in m.GOALS
            }
            # Renormalise to exactly 100 with integer largest-remainder rounding.
            total = sum(raw.values())
            weights = {goal: value * 100 // total for goal, value in raw.items()}
            by_remainder = sorted(
                m.GOALS, key=lambda g: (-(raw[g] * 100 % total), m.GOALS.index(g))
            )
            for goal in by_remainder[: 100 - sum(weights.values())]:
                weights[goal] += 1
            new = m.GoalWeights(**weights)
            if new == old:
                raise InvalidAction("bad_params", "Goal weights would not change")
            actor.goal_weights = new
            emit(
                "goals_changed",
                dict(citizen_id=actor.id, old=old.model_dump(), new=new.model_dump()),
            )
        elif isinstance(action, m.GatherResource):
            if RESOURCE_SOURCES.get(action.resource) != building.kind:
                raise InvalidAction(
                    "bad_params", f"{action.resource} cannot be gathered at a {building.kind}"
                )
            # Partial gathers are allowed: take what is left, up to the requested quantity.
            field = self._stock(action.resource)
            quantity = min(action.quantity, field.stock)
            field.stock -= quantity
            setattr(
                building.inventory,
                action.resource,
                getattr(building.inventory, action.resource) + quantity,
            )
            emit(
                "resource_gathered",
                dict(
                    citizen_id=actor.id,
                    building_id=building.id,
                    resource=action.resource,
                    requested=action.quantity,
                    quantity=quantity,
                    stock_remaining=field.stock,
                ),
            )
        elif isinstance(action, m.ApplyJob):
            if actor.employer_id in s.buildings:
                raise InvalidAction("already_employed", "Quit your current job before applying")
            if self._application(actor.id, building.id) is not None:
                raise InvalidAction("bad_params", f"Already applied to {building.name}")
            if self._free_slots(building) < 1:
                raise InvalidAction("no_free_slot", f"{building.name} has no free job slot")
            aid = f"application-{s.branch_id}-{s.sequence + 1}"
            s.job_applications[aid] = m.JobApplication(
                id=aid,
                citizen_id=actor.id,
                building_id=building.id,
                tick=s.tick,
                sequence=s.sequence,
            )
            emit(
                "job_applied",
                dict(application_id=aid, citizen_id=actor.id, building_id=building.id),
            )
        elif isinstance(action, m.QuitJob):
            employer = s.buildings.get(actor.employer_id)
            if employer is None:
                raise InvalidAction("bad_params", "You do not have a job to quit")
            actor.employer_id = None
            emit(
                "employment_changed",
                dict(citizen_id=actor.id, building_id=None, previous_building_id=employer.id),
            )
        elif isinstance(action, m.RejectApplication):
            application = self._application(action.citizen_id, building.id)
            if application is None:
                raise InvalidAction("bad_params", "No pending application from that citizen")
            self._resolve(application, "rejected", actor.id, action.rationale)
        elif isinstance(action, m.Lend):
            borrower = s.citizens.get(action.recipient_id)
            if borrower is None:
                raise InvalidAction("unknown_entity", "Unknown borrower")
            if borrower.id == actor.id:
                raise InvalidAction("bad_params", "Cannot lend to yourself")
            if action.due_tick <= s.tick:
                raise InvalidAction("bad_params", "Due tick must be in the future")
            if actor.money < action.principal:
                raise InvalidAction("insufficient_funds", "Insufficient funds for that principal")
            lid = f"loan-{s.branch_id}-{s.sequence + 1}"
            s.loans[lid] = m.Loan(
                id=lid,
                lender_id=actor.id,
                borrower_id=borrower.id,
                principal=action.principal,
                rate_bps=action.rate_bps,
                due_tick=action.due_tick,
                amount_owed=action.principal + action.principal * action.rate_bps // 10000,
                created_tick=s.tick,
            )
            emit("loan_offered", self._loan_payload(s.loans[lid]))
        elif isinstance(action, m.RespondLoan):
            loan = s.loans.get(action.loan_id)
            if loan is None:
                raise InvalidAction("unknown_entity", "Unknown loan")
            if loan.borrower_id != actor.id:
                raise InvalidAction("insufficient_authority", "Only the borrower may respond")
            if loan.status != "offered":
                raise InvalidAction("bad_params", f"Loan is {loan.status}, not offered")
            if not action.accept:
                loan.status = "declined"
                emit("loan_declined", self._loan_payload(loan))
            else:
                lender = s.citizens.get(loan.lender_id)
                if lender is None:
                    raise InvalidAction("unknown_entity", "Unknown lender")
                if loan.due_tick <= s.tick:
                    raise InvalidAction("bad_params", "Loan offer is past its due tick")
                if lender.money < loan.principal:
                    raise InvalidAction("insufficient_funds", "Lender can no longer fund the loan")
                lender.money -= loan.principal
                actor.money += loan.principal
                loan.status = "active"
                emit("loan_accepted", self._loan_payload(loan, loan.principal))
                emit(
                    "transaction_completed",
                    dict(sender_id=lender.id, recipient_id=actor.id, amount=loan.principal),
                )
        elif isinstance(action, m.Repay):
            loan = s.loans.get(action.loan_id)
            if loan is None:
                raise InvalidAction("unknown_entity", "Unknown loan")
            if loan.borrower_id != actor.id:
                raise InvalidAction("insufficient_authority", "Only the borrower may repay")
            if loan.status not in ("active", "defaulted"):
                raise InvalidAction("bad_params", f"Loan is {loan.status}; nothing to repay")
            remaining = loan.amount_owed - loan.amount_repaid
            if action.amount > remaining:
                raise InvalidAction("bad_params", f"Only {remaining} cents are still owed")
            if actor.money < action.amount:
                raise InvalidAction("insufficient_funds", "Insufficient funds")
            lender = s.citizens.get(loan.lender_id)
            if lender is None:
                raise InvalidAction("unknown_entity", "Unknown lender")
            actor.money -= action.amount
            lender.money += action.amount
            loan.amount_repaid += action.amount
            if loan.amount_repaid == loan.amount_owed:
                loan.status = "repaid"
            emit("loan_repaid", self._loan_payload(loan, action.amount))
            emit(
                "transaction_completed",
                dict(sender_id=actor.id, recipient_id=lender.id, amount=action.amount),
            )
        elif isinstance(action, m.Trade):
            self._offer_trade(actor, action)
        elif isinstance(action, m.RespondTrade):
            self._respond_trade(actor, action)
        elif isinstance(action, m.Research):
            invention = self._open_invention(action.invention_id)
            if action.mode == "money":
                spend = min(action.amount, invention.cost - invention.progress)
                if actor.money < spend:
                    raise InvalidAction("insufficient_funds", "Insufficient funds for research")
                actor.money -= spend  # Research spending leaves the economy (materials, trials).
                self._contribute(invention, actor, spend, "money", action.rationale)
            else:
                if actor.employer_id not in s.buildings:
                    raise InvalidAction(
                        "bad_params", "Time research forfeits wages; get a job first"
                    )
                if actor.research_invention_id is not None:
                    raise InvalidAction("bad_params", "Already researching on wage time")
                actor.research_invention_id = invention.id
                actor.research_start_tick = s.tick + 1
                actor.research_until_tick = s.tick + action.ticks
                emit(
                    "research_contributed",
                    dict(
                        invention_id=invention.id,
                        citizen_id=actor.id,
                        mode="time",
                        amount=0,
                        progress=invention.progress,
                        cost=invention.cost,
                        days_left=action.ticks,
                    ),
                )
        elif isinstance(action, m.LicenseInvention):
            invention = s.inventions.get(action.invention_id)
            if invention is None:
                raise InvalidAction("unknown_entity", "Unknown invention")
            if not invention.unlocked:
                raise InvalidAction("invention_locked", "Only unlocked inventions can be licensed")
            if invention.owner_id != actor.id:
                raise InvalidAction("not_owner", "Only the invention owner may license it")
            recipient = s.citizens.get(action.recipient_id)
            if recipient is None or recipient.id == actor.id:
                raise InvalidAction("bad_params", "Invalid recipient")
            if recipient.id in invention.licensees:
                raise InvalidAction("bad_params", f"{recipient.name} already holds a license")
            if any(
                o.invention_id == invention.id and o.recipient_id == recipient.id
                for o in s.license_offers.values()
            ):
                raise InvalidAction("bad_params", "An offer to this citizen is already pending")
            oid = f"license-{s.branch_id}-{s.sequence + 1}"
            offer = m.LicenseOffer(
                id=oid,
                invention_id=invention.id,
                owner_id=actor.id,
                recipient_id=recipient.id,
                fee=action.fee,
                tick=s.tick,
            )
            s.license_offers[oid] = offer
            emit("license_offered", self._offer_payload(offer))
        elif isinstance(action, m.RespondLicense):
            offer = s.license_offers.get(action.offer_id)
            if offer is None:
                raise InvalidAction("unknown_entity", "Unknown or expired license offer")
            if offer.recipient_id != actor.id:
                raise InvalidAction(
                    "insufficient_authority", "Only the recipient may answer this offer"
                )
            if s.tick > offer.tick + 1:
                raise InvalidAction("bad_params", "License offer has expired")
            invention = s.inventions[offer.invention_id]
            owner = s.citizens.get(offer.owner_id)
            if action.accept:
                if owner is None:
                    raise InvalidAction("unknown_entity", "The invention owner is gone")
                if actor.money < offer.fee:
                    raise InvalidAction("insufficient_funds", "Insufficient funds for the fee")
                actor.money -= offer.fee
                owner.money += offer.fee
                invention.licensees = sorted({*invention.licensees, actor.id})
                if offer.fee:
                    emit(
                        "transaction_completed",
                        dict(sender_id=actor.id, recipient_id=owner.id, amount=offer.fee),
                    )
            del s.license_offers[offer.id]
            status = "accepted" if action.accept else "declined"
            emit("license_resolved", dict(**self._offer_payload(offer), status=status))
        elif isinstance(action, m.AdoptInvention):
            invention = s.inventions.get(action.invention_id)
            if invention is None:
                raise InvalidAction("unknown_entity", "Unknown invention")
            if not invention.unlocked:
                raise InvalidAction("invention_locked", "The invention is not unlocked yet")
            if actor.id != invention.owner_id and actor.id not in invention.licensees:
                raise InvalidAction(
                    "insufficient_authority", "Adopting needs ownership or a license"
                )
            if building.kind != invention.effect.building_kind:
                raise InvalidAction(
                    "bad_params", f"{invention.name} only helps a {invention.effect.building_kind}"
                )
            if building.id in invention.adopters:
                raise InvalidAction("bad_params", "Already adopted here")
            if building.cash < invention.adoption_cost:
                raise InvalidAction("insufficient_funds", "The business cannot pay to adopt")
            building.cash -= invention.adoption_cost  # Tools and works leave the economy.
            invention.adopters = sorted({*invention.adopters, building.id})
            emit(
                "invention_adopted",
                dict(
                    invention_id=invention.id,
                    building_id=building.id,
                    cost=invention.adoption_cost,
                ),
            )
        elif isinstance(action, m.ProposeVote):
            if any(v.status == "open" for v in s.votes.values()):
                raise InvalidAction("bad_params", "Another town vote is already open")
            last = max((v.opens_tick for v in s.votes.values()), default=None)
            if last is not None and s.tick < last + VOTE_CADENCE_DAYS:
                raise InvalidAction(
                    "rate_limited", f"The next town vote may open on day {last + VOTE_CADENCE_DAYS}"
                )
            if action.kind == "market_tax" and action.value > 10000:
                raise InvalidAction("bad_params", "Market tax is at most 10000 basis points")
            if action.value == _policy(s.policies, action.kind):
                raise InvalidAction("bad_params", "That policy is already in force")
            vid = f"vote-{s.branch_id}-{s.sequence + 1}"
            s.votes[vid] = m.Vote(
                id=vid,
                proposer_id=actor.id,
                kind=action.kind,
                value=action.value,
                rationale=action.rationale,
                opens_tick=s.tick,
                closes_tick=s.tick + VOTE_DAYS,
            )
            emit(
                "vote_proposed",
                dict(
                    vote_id=vid,
                    kind=action.kind,
                    value=action.value,
                    closes_tick=s.tick + VOTE_DAYS,
                ),
            )
        elif isinstance(action, m.CastVote):
            vote = s.votes.get(action.vote_id)
            if vote is None:
                raise InvalidAction("unknown_entity", "Unknown vote")
            if vote.status != "open":
                raise InvalidAction("bad_params", "This vote is closed")
            previous = vote.ballots.get(actor.id)
            if previous == action.choice:
                raise InvalidAction("bad_params", f"Already voted {action.choice}")
            # A citizen may change their mind; the latest ballot replaces the earlier one.
            vote.ballots[actor.id] = action.choice
            emit(
                "vote_cast",
                dict(vote_id=vote.id, choice=action.choice, previous_choice=previous),
            )
        elif isinstance(action, m.LeaseLot):
            if plot.owner_id is None:
                raise InvalidAction("bad_params", "Town land has no landlord to lease from")
            if plot.owner_id == actor.id:
                raise InvalidAction("bad_params", "You already own this lot")
            if plot.tenant_id is not None:
                raise InvalidAction("lot_occupied", "The lot is already leased")
            if any(b.plot_id == plot.id for b in s.buildings.values()):
                raise InvalidAction("lot_occupied", "A building already stands on this lot")
            if actor.money < plot.rent:
                raise InvalidAction("insufficient_funds", "Cannot afford one period of rent")
            plot.tenant_id = actor.id
            plot.arrears = plot.missed_periods = plot.prepaid_periods = 0
            emit("lot_leased", _lot_payload(plot))
        elif isinstance(action, m.SetRent):
            old = plot.rent
            if action.rent == old:
                raise InvalidAction("bad_params", "Rent would not change")
            limit = max(old * MAX_RENT_CHANGE_PERCENT // 100, MIN_RENT_STEP)
            if plot.tenant_id is not None and abs(action.rent - old) > limit:
                raise InvalidAction(
                    "bad_params",
                    f"Rent may change by at most {MAX_RENT_CHANGE_PERCENT}% ({limit} cents)",
                )
            plot.rent = action.rent
            emit("rent_changed", dict(plot_id=plot.id, old_rent=old, new_rent=action.rent))
        elif isinstance(action, m.PayRent):
            if plot.tenant_id != actor.id:
                raise InvalidAction("bad_params", "You do not lease this lot")
            if plot.owner_id not in s.citizens:
                raise InvalidAction("unknown_entity", "The landlord no longer exists")
            if plot.arrears:
                amount = plot.arrears
            elif plot.rent == 0:
                raise InvalidAction("bad_params", "This lot has no rent to pay")
            elif plot.prepaid_periods >= MAX_PREPAID_PERIODS:
                raise InvalidAction(
                    "bad_params", f"Rent is already paid {MAX_PREPAID_PERIODS} periods ahead"
                )
            else:
                amount = plot.rent
            if actor.money < amount:
                raise InvalidAction("insufficient_funds", "Insufficient funds for rent")
            if plot.arrears:
                plot.arrears = plot.missed_periods = 0
            else:
                plot.prepaid_periods += 1
            self._pay_rent(plot, actor, amount, actor.id, action.rationale)
        elif isinstance(action, m.Evict):
            if plot.tenant_id is None:
                raise InvalidAction("bad_params", "The lot has no tenant")
            if plot.missed_periods < EVICTION_PERIODS:
                raise InvalidAction(
                    "bad_params",
                    f"Eviction needs {EVICTION_PERIODS} missed rent periods "
                    f"({plot.missed_periods} so far)",
                )
            evicted = _lot_payload(plot)
            for building in sorted(s.buildings.values(), key=lambda b: b.id):
                if building.plot_id == plot.id and building.owner_id == plot.tenant_id:
                    self._close(building, actor.id, action.rationale)
            plot.tenant_id = None
            plot.arrears = plot.missed_periods = plot.prepaid_periods = 0
            emit("tenant_evicted", evicted)
        elif isinstance(action, m.Interact):
            self._interact(actor, action)
        else:
            # Schemas are published ahead of their rules; never accept an action as a no-op.
            raise InvalidAction("not_supported", f"Action '{action.type}' is not supported yet")

    def _interact(self, actor: m.Citizen, action: m.Interact):
        """Bounded relationship change (spec section 5.2, scaled by 100).

        The target's feeling toward the actor always changes; ally and argue are mutual and
        change the actor's feeling toward the target too. One interact per actor and target
        per tick. Trust is clamped to -100..100, grudge and reputation to 0..100.
        """
        s = self.state
        target = s.citizens.get(action.recipient_id)
        if target is None:
            raise InvalidAction("unknown_entity", "Unknown citizen")
        if target.id == actor.id:
            raise InvalidAction("bad_params", "A citizen cannot interact with themselves")
        own = next((r for r in actor.relationships if r.citizen_id == target.id), None)
        if own is not None and own.last_interaction_tick == s.tick:
            raise InvalidAction("rate_limited", f"Already interacted with {target.name} today")
        theirs = next((r for r in target.relationships if r.citizen_id == actor.id), None)
        if action.kind == "ally" and (theirs.trust if theirs else 0) < ALLY_MIN_TRUST:
            raise InvalidAction(
                "trust_too_low", f"{target.name} must trust you at least {ALLY_MIN_TRUST} to ally"
            )
        amount = action.amount or 0
        if actor.money < amount:
            raise InvalidAction("insufficient_funds", "Insufficient funds")

        def emit(kind, payload, refs=None):
            return self.emit(kind, payload, actor.id, action.rationale, refs)

        if amount:
            actor.money -= amount
            target.money += amount
            emit(
                "transaction_completed",
                dict(sender_id=actor.id, recipient_id=target.id, amount=amount),
            )
        if action.kind == "insult":
            target.reputation = _clamp(target.reputation - INSULT_REPUTATION, 0, 100)
        elif action.kind == "mentor":
            target.reputation = _clamp(target.reputation + MENTOR_REPUTATION, 0, 100)
        elif action.kind == "betray":
            actor.reputation = _clamp(actor.reputation - BETRAY_REPUTATION, 0, 100)
        interaction = emit(
            "citizen_interacted",
            dict(
                recipient_id=target.id,
                kind=action.kind,
                amount=amount,
                actor_reputation=actor.reputation,
                recipient_reputation=target.reputation,
            ),
        )

        trust_delta, grudge_delta = INTERACTIONS[action.kind]
        own = _tie(actor, target.id)
        own.last_interaction_tick = s.tick
        changes = [(target, _tie(target, actor.id))]
        if action.kind in MUTUAL_INTERACTIONS:
            changes.append((actor, own))
        for holder, relation in changes:
            relation.trust = _clamp(relation.trust + trust_delta, -100, 100)
            relation.grudge = _clamp(relation.grudge + grudge_delta, 0, 100)
            if action.kind == "ally":
                relation.type = "ally"
            elif action.kind == "betray":
                relation.type = "rival"
            elif (
                action.kind == "befriend"
                and relation.type == "acquaintance"
                and relation.trust >= FRIEND_TRUST
            ):
                relation.type = "friend"
            emit("relationship_changed", _tie_payload(holder, relation), [interaction.id])

    def _stock(self, kind: str) -> m.ResourceStock:
        """The shared stock for kind; raises out_of_stock when missing or empty."""
        stock = self.state.resources.get(kind)
        if stock is None or stock.stock == 0:
            raise InvalidAction("out_of_stock", f"No {kind} left in the village stock")
        return stock

    def _regenerate_resources(self):
        """Daily step: each stock grows by regen_per_tick, bounded by its cap."""
        for kind in sorted(self.state.resources):
            stock = self.state.resources[kind]
            ceiling = stock.cap if stock.cap is not None else stock.stock + stock.regen_per_tick
            grown = max(0, min(stock.regen_per_tick, ceiling - stock.stock))
            if grown:
                stock.stock += grown
                self.emit(
                    "resource_regenerated", dict(resource=kind, quantity=grown, stock=stock.stock)
                )

    def _application(self, citizen_id: str, building_id: str) -> m.JobApplication | None:
        return next(
            (
                a
                for a in self.state.job_applications.values()
                if a.status == "pending"
                and a.citizen_id == citizen_id
                and a.building_id == building_id
            ),
            None,
        )

    def _free_slots(self, building: m.Building) -> int:
        staff = sum(1 for c in self.state.citizens.values() if c.employer_id == building.id)
        return building.job_slots - staff

    def _resolve(self, application: m.JobApplication, outcome: str, actor_id, rationale):
        """Close one pending application and tell the applicant how it ended.

        The record stays in job_applications with status hired (accepted) or rejected
        (rejected or withdrawn); the event keeps the finer-grained outcome.
        """
        application.status = "hired" if outcome == "accepted" else "rejected"
        self.emit(
            "job_application_resolved",
            dict(
                application_id=application.id,
                citizen_id=application.citizen_id,
                building_id=application.building_id,
                outcome=outcome,
            ),
            actor_id,
            rationale,
        )

    def _pay_rent(self, plot: m.Plot, tenant: m.Citizen, amount: int, actor_id, rationale):
        """Move rent from tenant to owner; money is conserved."""
        owner = self.state.citizens[plot.owner_id]
        tenant.money -= amount
        owner.money += amount
        self.emit(
            "transaction_completed",
            dict(sender_id=tenant.id, recipient_id=plot.owner_id, amount=amount),
            actor_id,
            rationale,
        )

    def _collect_tax(self, building: m.Building, amount: int, actor_id, rationale):
        """Market tax: a cut of the seller's revenue shared equally by every citizen.

        Each citizen (sorted by ID, buyer and owner included) gets floor(tax / n); the
        indivisible remainder stays with the seller, so money is conserved exactly.
        """
        recipients = sorted(self.state.citizens)
        tax = amount * self.state.policies.market_tax_bps // 10000
        share = tax // len(recipients) if recipients else 0
        if not share:
            return
        building.cash -= share * len(recipients)
        for cid in recipients:
            self.state.citizens[cid].money += share
        self.emit(
            "tax_collected",
            dict(
                building_id=building.id,
                amount=share * len(recipients),
                per_citizen=share,
                recipient_ids=recipients,
            ),
            actor_id,
            rationale,
        )

    def _boosted(self, building: m.Building, resource: str, quantity: int) -> int:
        """Apply adopted invention multipliers in invention ID order (integer, deterministic)."""
        for _, invention in sorted(self.state.inventions.items()):
            effect = invention.effect
            if (
                building.id in invention.adopters
                and effect.building_kind == building.kind
                and effect.resource == resource
            ):
                quantity = quantity * effect.multiplier_pct // 100
        return quantity

    def _researching(self, citizen: m.Citizen) -> bool:
        """True while a citizen's wages go to time-mode research instead of their pocket."""
        return (
            citizen.research_invention_id is not None
            and citizen.research_start_tick <= self.state.tick <= citizen.research_until_tick
        )

    def _open_invention(self, invention_id: str) -> m.Invention:
        invention = self.state.inventions.get(invention_id)
        if invention is None:
            raise InvalidAction("unknown_entity", "Unknown invention")
        if invention.unlocked:
            raise InvalidAction("bad_params", "Invention is already unlocked")
        return invention

    @staticmethod
    def _offer_payload(offer: m.LicenseOffer) -> dict:
        return dict(
            offer_id=offer.id,
            invention_id=offer.invention_id,
            owner_id=offer.owner_id,
            recipient_id=offer.recipient_id,
            fee=offer.fee,
        )

    def _contribute(self, invention: m.Invention, citizen: m.Citizen, amount, mode, rationale=None):
        """Add progress; at full cost the top contributor (lowest ID on ties) owns it."""
        invention.progress += amount
        invention.contributors[citizen.id] = invention.contributors.get(citizen.id, 0) + amount
        days_left = max(0, citizen.research_until_tick - self.state.tick) if mode == "time" else 0
        self.emit(
            "research_contributed",
            dict(
                invention_id=invention.id,
                citizen_id=citizen.id,
                mode=mode,
                amount=amount,
                progress=invention.progress,
                cost=invention.cost,
                days_left=days_left,
            ),
            citizen.id,
            rationale,
        )
        if invention.progress < invention.cost:
            return
        invention.unlocked = True
        invention.owner_id = min(
            invention.contributors, key=lambda c: (-invention.contributors[c], c)
        )
        released = []
        for other in sorted(self.state.citizens.values(), key=lambda c: c.id):
            if other.research_invention_id == invention.id:
                other.research_invention_id = None
                other.research_start_tick = 0
                other.research_until_tick = 0
                released.append(other.id)
        self.emit(
            "invention_unlocked",
            dict(
                invention_id=invention.id,
                owner_id=invention.owner_id,
                released_researcher_ids=released,
            ),
            citizen.id,
            rationale,
        )

    def _hire(self, application: m.JobApplication, actor_id, rationale):
        """Accept an application; the new employee's other applications are withdrawn."""
        s = self.state
        self._resolve(application, "accepted", actor_id, rationale)
        s.citizens[application.citizen_id].employer_id = application.building_id
        self.emit(
            "employment_changed",
            dict(citizen_id=application.citizen_id, building_id=application.building_id),
            actor_id,
            rationale,
        )
        for other in sorted(s.job_applications.values(), key=lambda a: a.sequence):
            if other.status == "pending" and other.citizen_id == application.citizen_id:
                self._resolve(other, "withdrawn", None, "Applicant took another job")

    def _resolve_job_applications(self):
        """Daily fallback for applications the owner left unanswered since the last tick.

        Owners prefer applicants they trust: applications are taken in order of the owner's
        trust toward the applicant (highest first; no entry counts as 0), then first come,
        first served. An applicant who is still unemployed is hired while the business has a
        free slot and cash for one day's wage; otherwise the application is rejected.
        Applications whose citizen or business is gone, or whose applicant already found work,
        are withdrawn.
        """
        s = self.state

        def owner_trust(application: m.JobApplication) -> int:
            building = s.buildings.get(application.building_id)
            owner = s.citizens.get(building.owner_id) if building is not None else None
            if owner is None:
                return 0
            return next(
                (r.trust for r in owner.relationships if r.citizen_id == application.citizen_id),
                0,
            )

        pending = sorted(
            (a for a in s.job_applications.values() if a.status == "pending"),
            key=lambda a: (-owner_trust(a), a.sequence),
        )
        for application in pending:
            if application.tick >= s.tick:
                continue  # Give the owner the next queued-action round to answer.
            if application.status != "pending":
                continue  # Withdrawn by an earlier hire this tick.
            applicant = s.citizens.get(application.citizen_id)
            building = s.buildings.get(application.building_id)
            if applicant is None or building is None or applicant.employer_id in s.buildings:
                self._resolve(application, "withdrawn", None, "Application no longer valid")
            elif self._free_slots(building) < 1:
                self._resolve(application, "rejected", building.owner_id, "No free job slot")
            elif building.cash < building.wage:
                self._resolve(application, "rejected", building.owner_id, "Cannot afford wage")
            else:
                self._hire(application, building.owner_id, "Free slot and wage covered")

    def _innovation_day(self):
        """Expire unanswered license offers, then credit each time researcher's forfeited wage."""
        s = self.state
        for oid in sorted(s.license_offers):
            offer = s.license_offers[oid]
            if s.tick > offer.tick + 1:
                del s.license_offers[oid]
                self.emit("license_resolved", dict(**self._offer_payload(offer), status="expired"))
        for citizen in sorted(s.citizens.values(), key=lambda c: c.id):
            if not self._researching(citizen):
                continue
            invention = s.inventions.get(citizen.research_invention_id)
            employer = s.buildings.get(citizen.employer_id)
            last_day = s.tick >= citizen.research_until_tick
            if invention is not None and not invention.unlocked:
                wage = employer.wage if employer else 0  # Losing the job ends the forfeit.
                self._contribute(
                    invention, citizen, min(wage, invention.cost - invention.progress), "time"
                )
            if last_day and citizen.research_invention_id is not None:
                citizen.research_invention_id = None
                citizen.research_start_tick = 0
                citizen.research_until_tick = 0

    def _settle_votes(self):
        """Daily: close votes that have been open VOTE_DAYS days, apply passed policies, and
        keep every business within the policies in force (also catches new businesses)."""
        from kronos_sim.queries import vote_tally

        s = self.state
        for vote in sorted(s.votes.values(), key=lambda v: v.id):
            if vote.status != "open" or s.tick < vote.closes_tick:
                continue
            tally = vote_tally(s, vote)
            # Weighted by influence over ballots cast; abstaining carries no weight.
            passed = tally.yes_weight * 2 > tally.yes_weight + tally.no_weight
            vote.status = "passed" if passed else "failed"
            vote.yes_weight, vote.no_weight = tally.yes_weight, tally.no_weight
            closed = self.emit(
                "vote_closed",
                dict(
                    vote_id=vote.id,
                    kind=vote.kind,
                    value=vote.value,
                    passed=passed,
                    yes_weight=tally.yes_weight,
                    no_weight=tally.no_weight,
                ),
            )
            if passed:
                old = _policy(s.policies, vote.kind)
                field = "market_tax_bps" if vote.kind == "market_tax" else vote.kind
                setattr(s.policies, field, vote.value)
                self.emit(
                    "policy_changed",
                    dict(kind=vote.kind, old_value=old, new_value=vote.value),
                    causal_refs=[closed.id],
                )
                self._enforce_policies([closed.id])
        self._enforce_policies([])

    def _enforce_policies(self, causal_refs: list[str]):
        """Raise wages below the minimum and lower bread prices above the cap."""
        s = self.state
        for building in sorted(s.buildings.values(), key=lambda b: b.id):
            if building.wage < s.policies.min_wage:
                old, building.wage = building.wage, s.policies.min_wage
                self.emit(
                    "wage_changed",
                    dict(building_id=building.id, old_wage=old, new_wage=building.wage),
                    rationale="Town minimum wage",
                    causal_refs=causal_refs,
                )
            cap = s.policies.bread_price_cap
            if cap and building.prices.get("bread", 0) > cap:
                old, building.prices["bread"] = building.prices["bread"], cap
                self.emit(
                    "price_changed",
                    dict(building_id=building.id, resource="bread", old_price=old, new_price=cap),
                    rationale="Town bread price cap",
                    causal_refs=causal_refs,
                )

    def _collect_rent(self):
        """Every RENT_PERIOD_DAYS: each tenant pays from prepaid periods or money, else falls
        into arrears. Lots are processed in ID order; free (rent 0) leases are skipped."""
        if self.state.tick % RENT_PERIOD_DAYS:
            return
        for plot in sorted(self.state.plots.values(), key=lambda p: p.id):
            tenant = self.state.citizens.get(plot.tenant_id)
            if tenant is None or plot.owner_id not in self.state.citizens or plot.rent == 0:
                continue
            if plot.prepaid_periods:
                plot.prepaid_periods -= 1
                self.emit("rent_covered", _lot_payload(plot), tenant.id)
            elif tenant.money >= plot.rent:
                self._pay_rent(plot, tenant, plot.rent, tenant.id, "Scheduled rent")
            else:
                plot.arrears += plot.rent
                plot.missed_periods += 1
                self.emit("rent_missed", _lot_payload(plot), tenant.id)

    def _close(self, building: m.Building, actor_id: str | None, rationale: str | None):
        """Remove a business: cash and goods go to the owner, pending applications are
        rejected and employees are released."""
        s = self.state
        owner = s.citizens.get(building.owner_id)
        if owner is not None:
            if building.cash:
                owner.money += building.cash
                self.emit(
                    "transaction_completed",
                    dict(sender_id=building.id, recipient_id=owner.id, amount=building.cash),
                    actor_id,
                    rationale,
                )
            for resource in ("wheat", "bread"):
                quantity = getattr(building.inventory, resource)
                if quantity:
                    setattr(
                        owner.inventory, resource, getattr(owner.inventory, resource) + quantity
                    )
                    self.emit(
                        "transaction_completed",
                        dict(
                            sender_id=building.id,
                            recipient_id=owner.id,
                            amount=0,
                            resource=resource,
                            quantity=quantity,
                        ),
                        actor_id,
                        rationale,
                    )
        for application in sorted(s.job_applications.values(), key=lambda a: a.sequence):
            if application.status == "pending" and application.building_id == building.id:
                self._resolve(application, "rejected", actor_id, "Business closed")
        for worker in sorted(s.citizens.values(), key=lambda c: c.id):
            if worker.employer_id == building.id:
                worker.employer_id = None
                self.emit(
                    "employment_changed",
                    dict(citizen_id=worker.id, building_id=None, previous_building_id=building.id),
                    actor_id,
                    rationale,
                )
        if owner is not None:
            remember(owner, f"{building.name} closed" + (f" ({rationale})" if rationale else ""))
        del s.buildings[building.id]
        self.emit(
            "building_removed",
            dict(entity_id=building.id, position=building.position.model_dump()),
            actor_id,
            rationale,
        )

    @staticmethod
    def _loan_payload(loan: m.Loan, amount: int = 0) -> dict:
        return dict(
            loan_id=loan.id,
            lender_id=loan.lender_id,
            borrower_id=loan.borrower_id,
            status=loan.status,
            principal=loan.principal,
            amount_owed=loan.amount_owed,
            amount_repaid=loan.amount_repaid,
            amount=amount,
        )

    def _settle_loans(self):
        """Daily: expire unanswered offers on their due tick; default active loans past it.

        A default applies its penalties exactly once (the status leaves "active"): the lender's
        trust toward the borrower drops and the borrower's reputation falls.
        """
        s = self.state
        for lid in sorted(s.loans):
            loan = s.loans[lid]
            if loan.status == "offered" and s.tick >= loan.due_tick:
                loan.status = "expired"
                self.emit("loan_expired", self._loan_payload(loan), loan.lender_id)
            elif loan.status == "active" and s.tick > loan.due_tick:
                loan.status = "defaulted"
                lender = s.citizens.get(loan.lender_id)
                borrower = s.citizens.get(loan.borrower_id)
                trust = 0
                if lender is not None:
                    relation = _tie(lender, loan.borrower_id)
                    relation.trust = max(-100, relation.trust - DEFAULT_TRUST_PENALTY)
                    relation.grudge = min(100, relation.grudge + DEFAULT_GRUDGE)
                    trust = relation.trust
                reputation = 0
                if borrower is not None:
                    borrower.reputation = max(0, borrower.reputation - DEFAULT_REPUTATION_PENALTY)
                    reputation = borrower.reputation
                default = self.emit(
                    "loan_defaulted",
                    dict(
                        **self._loan_payload(loan),
                        borrower_reputation=reputation,
                        lender_trust=trust,
                    ),
                    loan.borrower_id,
                )
                if lender is not None:
                    # Same convention as communicate: recipient's trust toward the actor.
                    self.emit(
                        "relationship_changed",
                        _tie_payload(lender, relation),
                        loan.borrower_id,
                        causal_refs=[default.id],
                    )

    @staticmethod
    def _check_holds(holder: m.Citizen, bundle: m.TradeBundle):
        if holder.money < bundle.money:
            raise InvalidAction(
                "insufficient_funds", f"{holder.name} lacks the money for this trade"
            )
        for resource, quantity in bundle.goods.model_dump().items():
            if getattr(holder.inventory, resource) < quantity:
                raise InvalidAction("out_of_stock", f"{holder.name} lacks the {resource}")

    def _offer_trade(self, actor: m.Citizen, action: m.Trade):
        s = self.state
        recipient = s.citizens.get(action.recipient_id)
        if recipient is None:
            raise InvalidAction("unknown_entity", "Unknown recipient")
        if recipient.id == actor.id:
            raise InvalidAction("bad_params", "Cannot trade with yourself")
        for side in (action.give, action.get):
            if not side.money and not any(side.goods.model_dump().values()):
                raise InvalidAction("bad_params", "Both sides of a trade must be non-empty")
        pending = [o for o in s.trade_offers.values() if o.offerer_id == actor.id]
        if len(pending) >= MAX_PENDING_OFFERS:
            raise InvalidAction(
                "rate_limited", f"At most {MAX_PENDING_OFFERS} pending offers per citizen"
            )
        self._check_holds(actor, action.give)
        offer = m.TradeOffer(
            id=f"offer-{s.branch_id}-{s.sequence + 1}",
            offerer_id=actor.id,
            recipient_id=recipient.id,
            give=action.give.model_copy(deep=True),
            get=action.get.model_copy(deep=True),
            created_tick=s.tick,
            expires_tick=s.tick + OFFER_TTL_DAYS,
            rationale=action.rationale,
        )
        event = self.emit(
            "trade_offered",
            dict(
                offer_id=offer.id,
                sender_id=actor.id,
                recipient_id=recipient.id,
                give=offer.give.model_dump(),
                get=offer.get.model_dump(),
                expires_tick=offer.expires_tick,
            ),
            actor.id,
            action.rationale,
        )
        offer.event_id = event.id
        s.trade_offers[offer.id] = offer

    def _respond_trade(self, actor: m.Citizen, action: m.RespondTrade):
        s = self.state
        offer = s.trade_offers.get(action.offer_id)
        if offer is None:
            raise InvalidAction("unknown_entity", "No pending offer with that ID")
        if offer.recipient_id != actor.id:
            raise InvalidAction("insufficient_authority", "Only the recipient may respond")
        if s.tick > offer.expires_tick:
            raise InvalidAction("bad_params", "Trade offer has expired")
        offerer = s.citizens.get(offer.offerer_id)
        if offerer is None:
            raise InvalidAction("unknown_entity", "The offerer no longer exists")
        refs = [offer.event_id] if offer.event_id else []
        if not action.accept:
            self._resolve_offer(offer, "trade_declined", actor.id, action.rationale, refs)
            return
        self._check_holds(offerer, offer.give)
        self._check_holds(actor, offer.get)
        accepted = self._resolve_offer(offer, "trade_accepted", actor.id, action.rationale, refs)
        for source, target, bundle in ((offerer, actor, offer.give), (actor, offerer, offer.get)):
            if bundle.money:
                source.money -= bundle.money
                target.money += bundle.money
                self.emit(
                    "transaction_completed",
                    dict(sender_id=source.id, recipient_id=target.id, amount=bundle.money),
                    actor.id,
                    action.rationale,
                    [accepted.id],
                )
            for resource, quantity in bundle.goods.model_dump().items():
                if not quantity:
                    continue
                setattr(source.inventory, resource, getattr(source.inventory, resource) - quantity)
                setattr(target.inventory, resource, getattr(target.inventory, resource) + quantity)
                self.emit(
                    "transaction_completed",
                    dict(
                        sender_id=source.id,
                        recipient_id=target.id,
                        amount=0,
                        resource=resource,
                        quantity=quantity,
                    ),
                    actor.id,
                    action.rationale,
                    [accepted.id],
                )

    def _resolve_offer(self, offer: m.TradeOffer, kind: str, actor_id, rationale, refs):
        """Remove a pending offer, tell the offerer, and log the outcome."""
        s = self.state
        del s.trade_offers[offer.id]
        return self.emit(
            kind,
            dict(offer_id=offer.id, sender_id=offer.offerer_id, recipient_id=offer.recipient_id),
            actor_id,
            rationale,
            refs,
        )

    def _expire_offers(self):
        """Daily: drop offers past their last day or whose parties no longer exist."""
        s = self.state
        for offer_id in sorted(s.trade_offers):
            offer = s.trade_offers[offer_id]
            parties_gone = (
                offer.offerer_id not in s.citizens or offer.recipient_id not in s.citizens
            )
            if parties_gone or s.tick > offer.expires_tick:
                refs = [offer.event_id] if offer.event_id else []
                self._resolve_offer(offer, "trade_expired", None, "Offer expired", refs)

    def _add_citizen(self, cid: str, plot: m.Plot, **fields) -> m.Citizen:
        """Place a new citizen by a lot and announce it (spawn route and newcomers)."""
        citizen = m.Citizen(id=cid, position=m.Position(x=plot.position.x, z=0), **fields)
        self.state.citizens[cid] = citizen
        self.emit("citizen_spawned", dict(entity_id=cid, position=citizen.position.model_dump()))
        return citizen

    @staticmethod
    def _numbered(ids, prefix: str) -> list[int]:
        return [
            int(i[len(prefix) :])
            for i in ids
            if i.startswith(prefix) and i[len(prefix) :].isdigit()
        ]

    def _plot_order(self) -> list[m.Plot]:
        """Lots in numeric ID order (plot-2 before plot-10), then any other IDs."""

        def key(plot: m.Plot):
            n = self._numbered([plot.id], "plot-")
            return (0, n[0], "") if n else (1, 0, plot.id)

        return sorted(self.state.plots.values(), key=key)

    def _let_destitute_leave(self):
        """A citizen at hunger 100 with no money for LEAVE_AFTER_DAYS days in a row leaves,
        unless they own a building or a lot. Their job, lease, pending applications and
        pending offers end first so nothing points at them."""
        s = self.state
        owners = {b.owner_id for b in s.buildings.values()} | {
            p.owner_id for p in s.plots.values() if p.owner_id is not None
        }
        for citizen in sorted(s.citizens.values(), key=lambda c: c.id):
            destitute = citizen.hunger == 100 and citizen.money == 0
            citizen.destitute_days = citizen.destitute_days + 1 if destitute else 0
            if citizen.destitute_days >= LEAVE_AFTER_DAYS and citizen.id not in owners:
                self._remove_citizen(citizen, "Starving and penniless; left the village")

    def _remove_citizen(self, citizen: m.Citizen, rationale: str):
        s = self.state
        employer = s.buildings.get(citizen.employer_id)
        if citizen.employer_id is not None:
            citizen.employer_id = None
            self.emit(
                "employment_changed",
                dict(
                    citizen_id=citizen.id,
                    building_id=None,
                    previous_building_id=employer.id if employer else None,
                ),
                citizen.id,
                rationale,
            )
        for plot in self._plot_order():
            if plot.tenant_id == citizen.id:
                ended = _lot_payload(plot)  # arrears here are the written-off debt
                plot.tenant_id = None
                plot.arrears = plot.missed_periods = plot.prepaid_periods = 0
                self.emit("tenant_evicted", ended, citizen.id, rationale)
        for application in sorted(s.job_applications.values(), key=lambda a: a.sequence):
            if application.status == "pending" and application.citizen_id == citizen.id:
                self._resolve(application, "rejected", None, rationale)
        for lid in sorted(s.loans):
            loan = s.loans[lid]
            if loan.status == "offered" and citizen.id in (loan.lender_id, loan.borrower_id):
                loan.status = "expired"
                self.emit("loan_expired", self._loan_payload(loan), citizen.id, rationale)
        for offer_id in sorted(s.trade_offers):
            offer = s.trade_offers[offer_id]
            if citizen.id in (offer.offerer_id, offer.recipient_id):
                refs = [offer.event_id] if offer.event_id else []
                self._resolve_offer(offer, "trade_expired", None, rationale, refs)
        for oid in sorted(s.license_offers):
            offer = s.license_offers[oid]
            if citizen.id in (offer.owner_id, offer.recipient_id):
                del s.license_offers[oid]
                self.emit("license_resolved", dict(**self._offer_payload(offer), status="expired"))
        del s.citizens[citizen.id]
        self.emit(
            "citizen_removed",
            dict(entity_id=citizen.id, position=citizen.position.model_dump()),
            citizen.id,
            rationale,
        )

    def _pay_out_surplus(self):
        """Business cash above BUSINESS_CASH_CAP is shared evenly by its employees (ID order);
        the remainder, or everything when there is no staff, goes to the owner."""
        s = self.state
        for building in sorted(s.buildings.values(), key=lambda b: b.id):
            surplus = building.cash - BUSINESS_CASH_CAP
            owner = s.citizens.get(building.owner_id)
            if surplus <= 0:
                continue
            staff = sorted(c.id for c in s.citizens.values() if c.employer_id == building.id)
            share = surplus // len(staff) if staff else 0
            payouts = {cid: share for cid in staff if share}
            if owner is not None and surplus - share * len(staff):
                payouts[owner.id] = payouts.get(owner.id, 0) + surplus - share * len(staff)
            for cid, amount in sorted(payouts.items()):
                building.cash -= amount
                s.citizens[cid].money += amount
                self.emit(
                    "transaction_completed",
                    dict(sender_id=building.id, recipient_id=cid, amount=amount),
                    building.owner_id,
                    "Surplus paid out to the people who earned it",
                )

    def spawn(self, request: m.SpawnCitizenRequest) -> m.SimulationTickResult:
        tx = Engine(self.state)
        tx._spawn(request)
        return tx.result()

    def _spawn(self, request: m.SpawnCitizenRequest) -> str:
        plot = self.state.plots.get(request.plot_id)
        if plot is None:
            raise InvalidAction("unknown_entity", "Unknown plot")
        cid = f"citizen-{self.state.branch_id}-{self.state.sequence + 1}"
        self._add_citizen(  # emits citizen_spawned
            cid,
            plot,
            name=request.name,
            occupation=request.occupation,
            money=request.money,
            personality=request.personality,
            goal_weights=request.goal_weights,
        )
        return cid

    def intervene(
        self, command: m.Intervention, text: str, action_id: str | None = None
    ) -> m.SimulationTickResult:
        """Apply one parsed player intervention as a single validated transaction.

        Emits intervention_applied (payload `kind` names the command) first, then the concrete
        events it caused (price_changed, wage_changed, transaction_completed, policy_changed),
        each citing it in causal_refs. Invalid commands raise InvalidAction("bad_params", ...).
        """
        tx = Engine(self.state)
        tx.action_id = action_id  # the queued attempt this intervention resolves
        handlers = {
            "modify_price": tx._intervene_price,
            "set_wage": tx._intervene_wage,
            "grant_money": tx._intervene_grant,
            "adjust_resource": tx._intervene_resource,
            "adjust_hunger": tx._intervene_hunger,
            "set_policy": tx._intervene_policy,
        }
        plan, scope, affected = handlers[command.type](command)
        payload = dict(
            text=text,
            kind=command.type,
            scope=scope,
            percent=getattr(command, "percent", None),
            command=command.model_dump(),
            affected_ids=affected,
        )
        intervention = tx.emit("intervention_applied", payload)
        for kind, event in plan(intervention.id):
            tx.emit(kind, event, causal_refs=[intervention.id])
        return tx.result()

    def _targets(self, citizen_id: str | None) -> list[m.Citizen]:
        if citizen_id is None:
            return [self.state.citizens[c] for c in sorted(self.state.citizens)]
        if citizen_id not in self.state.citizens:
            raise InvalidAction("unknown_entity", "Unknown citizen")
        return [self.state.citizens[citizen_id]]

    @staticmethod
    def _scaled(value: int, percent: int) -> int:
        return int(
            (Decimal(value) * (100 + percent) / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )

    def _intervene_price(self, command: m.PriceIntervention):
        targets = sorted(
            (b for b in self.state.buildings.values() if b.kind == "bakery"), key=lambda b: b.id
        )
        prices = [self._scaled(b.prices["bread"], command.percent) for b in targets]
        if not targets or any(p < 1 or p > 1000000 for p in prices):
            raise InvalidAction("bad_params", "No bakery or resulting price out of bounds")
        cap = self.state.policies.bread_price_cap
        if cap and any(p > cap for p in prices):
            raise InvalidAction("bad_params", f"The town caps bread at {cap} cents")

        def plan(_):
            for building, price in zip(targets, prices, strict=True):
                old, building.prices["bread"] = building.prices["bread"], price
                yield (
                    "price_changed",
                    dict(building_id=building.id, resource="bread", old_price=old, new_price=price),
                )

        return plan, "all_bakeries", [b.id for b in targets]

    def _intervene_wage(self, command: m.WageIntervention):
        targets = sorted(self.state.buildings.values(), key=lambda b: b.id)
        wages = [
            command.wage if command.wage is not None else self._scaled(b.wage, command.percent)
            for b in targets
        ]
        if not targets:
            raise InvalidAction("bad_params", "There is no business to pay wages")
        if any(w < 1 or w > 1000000 for w in wages):
            raise InvalidAction("bad_params", "Resulting wage out of bounds")
        floor = self.state.policies.min_wage
        if any(w < floor for w in wages):
            raise InvalidAction("bad_params", f"The town minimum wage is {floor} cents")
        changed = [(b, w) for b, w in zip(targets, wages, strict=True) if b.wage != w]
        if not changed:
            raise InvalidAction("bad_params", "Wages would not change")

        def plan(_):
            for building, wage in changed:
                old, building.wage = building.wage, wage
                yield "wage_changed", dict(building_id=building.id, old_wage=old, new_wage=wage)

        return plan, "all_businesses", [b.id for b, _ in changed]

    def _intervene_grant(self, command: m.GrantIntervention):
        # Taking never drives money below zero; citizens with nothing to take are skipped.
        moves = [
            (c, command.amount if command.amount > 0 else -min(-command.amount, c.money))
            for c in self._targets(command.citizen_id)
        ]
        moves = [(c, delta) for c, delta in moves if delta]
        if not moves:
            raise InvalidAction("insufficient_funds", "Nobody has money to take")

        def plan(_):
            for citizen, delta in moves:
                citizen.money += delta
                sender, recipient = ("town", citizen.id) if delta > 0 else (citizen.id, "town")
                yield (
                    "transaction_completed",
                    dict(sender_id=sender, recipient_id=recipient, amount=abs(delta)),
                )

        scope = "all_citizens" if command.citizen_id is None else "citizen"
        return plan, scope, [c.id for c, _ in moves]

    def _intervene_resource(self, command: m.ResourceIntervention):
        stock = self.state.resources.get(command.resource)
        if stock is None:
            raise InvalidAction("unknown_entity", f"The village has no {command.resource} stock")
        new_stock = max(0, stock.stock + command.stock_change)
        regen = stock.regen_per_tick if command.regen_per_tick is None else command.regen_per_tick
        if (new_stock, regen) == (stock.stock, stock.regen_per_tick):
            raise InvalidAction("bad_params", f"The {command.resource} stock would not change")
        stock.stock, stock.regen_per_tick = new_stock, regen
        return (lambda _: iter(())), command.resource, []

    def _intervene_hunger(self, command: m.HungerIntervention):
        changes = [
            (c, _clamp(c.hunger + command.change, 0, 100))
            for c in self._targets(command.citizen_id)
        ]
        changes = [(c, hunger) for c, hunger in changes if hunger != c.hunger]
        if not changes:
            raise InvalidAction("bad_params", "Hunger would not change")
        for citizen, hunger in changes:
            citizen.hunger = hunger
        scope = "all_citizens" if command.citizen_id is None else "citizen"
        return (lambda _: iter(())), scope, [c.id for c, _ in changes]

    def _intervene_policy(self, command: m.PolicyIntervention):
        policies = self.state.policies
        old = _policy(policies, command.kind)
        if old == command.value:
            raise InvalidAction("bad_params", "That policy is already in force")

        def plan(intervention_id):
            field = "market_tax_bps" if command.kind == "market_tax" else command.kind
            setattr(policies, field, command.value)
            yield "policy_changed", dict(kind=command.kind, old_value=old, new_value=command.value)
            self._enforce_policies([intervention_id])

        return plan, "town", []

    def tick(
        self,
        proposals: list[m.AgentAction] | None = None,
        *,
        queued: list[m.ActionResult] | None = None,
    ) -> m.SimulationTickResult:
        tx = Engine(self.state)
        tx.state.tick += 1
        batch = list(queued or [])
        # Pure-module callers can still supply proposals; API callers freeze runtime records.
        for index, action in enumerate(proposals or [], 1):
            batch.append(
                m.ActionResult(
                    action_id=f"proposal-{tx.state.branch_id}:{tx.state.tick}:{index}",
                    branch_id=tx.state.branch_id,
                    status="queued",
                    action=action,
                    order=index,
                    scheduled_tick=tx.state.tick,
                    tick=self.state.tick,
                    sequence=self.state.sequence,
                )
            )
        outcomes = []
        seen = set()
        # Player interventions first, then stable citizen ID and runtime submission ordinal.
        # Provider completion order cannot reorder different citizens' actions.
        for record in sorted(
            batch,
            key=lambda r: (
                0 if isinstance(r.action, INTERVENTIONS) else 1,
                getattr(r.action, "actor_id", ""),
                r.order,
                r.action_id,
            ),
        ):
            if (
                record.status != "queued"
                or record.branch_id != tx.state.branch_id
                or record.scheduled_tick > tx.state.tick
                or record.action_id in seen
            ):
                continue
            seen.add(record.action_id)
            action = record.action
            error = None
            try:
                update = (
                    Engine(tx.state).intervene(action, record.text or "", record.action_id)
                    if isinstance(action, INTERVENTIONS)
                    else Engine(tx.state).apply(action, record.action_id)
                )
            except InvalidAction as exc:
                error = exc
                if isinstance(action, INTERVENTIONS):
                    rejected = Engine(tx.state)
                    rejected.action_id = record.action_id
                    rejected.emit(
                        "action_rejected",
                        dict(action_type=action.type, code=exc.code, message=str(exc)),
                    )
                    update = rejected.result()
                else:
                    update = Engine(tx.state).reject(action, exc, record.action_id)
            tx.state = update.state
            tx.rng.setstate(_tuples(update.state.rng_state))
            tx.events.extend(update.events)
            outcomes.append(
                record.model_copy(
                    update=dict(
                        status="rejected" if error else "applied",
                        tick=tx.state.tick,
                        event_ids=[event.id for event in update.events],
                        error=error.code if error else None,
                        message=str(error) if error else None,
                    )
                )
            )
        tx._automatic_rules()
        tx._growth_rules()
        tx.emit("tick_completed", {"actions": len(outcomes)})
        for outcome in outcomes:
            outcome.sequence = tx.state.sequence
        result = tx.result([r.message for r in outcomes if r.status == "rejected"])
        result.action_results = outcomes
        return result

    def _automatic_rules(self):
        """Daily mechanics; strategic proposals have already been resolved."""
        s = self.state
        self._resolve_job_applications()
        # Business-to-business wheat purchase, then production; no free resource teleportation.
        farms = sorted((b for b in s.buildings.values() if b.kind == "farm"), key=lambda b: b.id)
        for building in sorted(s.buildings.values(), key=lambda b: (b.kind != "farm", b.id)):
            if building.kind == "bakery" and building.inventory.wheat < 2 and farms:
                farm = farms[0]
                amount = farm.prices["wheat"] * 2
                if farm.inventory.wheat >= 2 and building.cash >= amount:
                    farm.inventory.wheat -= 2
                    building.inventory.wheat += 2
                    farm.cash += amount
                    building.cash -= amount
                    self.emit(
                        "transaction_completed",
                        dict(
                            sender_id=building.id,
                            recipient_id=farm.id,
                            amount=amount,
                            resource="wheat",
                            quantity=2,
                        ),
                    )
            if building.kind != "market":
                try:
                    self._execute(m.Produce(actor_id=building.owner_id, building_id=building.id))
                except InvalidAction:
                    pass  # Scarcity is a valid economic outcome.
        missed_payroll = set()
        for citizen in sorted(s.citizens.values(), key=lambda c: c.id):
            # Time-mode researchers forfeit today's wage; _innovation_day credits it as progress.
            employer = None if self._researching(citizen) else s.buildings.get(citizen.employer_id)
            if employer and employer.cash >= employer.wage:
                employer.cash -= employer.wage
                citizen.money += employer.wage
                self.emit(
                    "transaction_completed",
                    dict(sender_id=employer.id, recipient_id=citizen.id, amount=employer.wage),
                    citizen.id,
                )
            elif employer:
                missed_payroll.add(employer.id)
            citizen.hunger = min(100, citizen.hunger + 20)
            if citizen.inventory.bread and citizen.hunger >= 20:
                self._execute(m.Consume(actor_id=citizen.id))
            if s.plots:
                self._execute(
                    m.MoveTo(actor_id=citizen.id, plot_id=self.rng.choice(sorted(s.plots)))
                )
        for building in sorted(s.buildings.values(), key=lambda b: b.id):
            building.unpaid_days = building.unpaid_days + 1 if building.id in missed_payroll else 0
            if building.unpaid_days >= BANKRUPTCY_DAYS:
                self._close(building, None, f"Bankrupt: wages unpaid for {BANKRUPTCY_DAYS} days")
        self._regenerate_resources()
        self._settle_loans()
        self._expire_offers()
        self._innovation_day()
        self._settle_votes()
        self._collect_rent()

    def _upgrade(self, building: m.Building, rationale=None, *, business_pays=False):
        """One upgrade rule for owner commands and automatic reinvestment."""
        if building.level >= 3 or building.job_slots > 18:
            raise InvalidAction("bad_params", "Building is at its level or job-slot limit")
        owner = self.state.citizens[building.owner_id]
        balance = building.cash if business_pays else owner.money
        if balance < 2500:
            raise InvalidAction("insufficient_funds", "Upgrade costs 25 coins")
        if business_pays:
            building.cash -= 2500
        else:
            owner.money -= 2500
        building.level += 1
        building.job_slots += 2
        self.emit(
            "building_upgraded",
            dict(entity_id=building.id, level=building.level),
            owner.id,
            rationale,
        )

    def _growth_rules(self):
        """V1 deterministic growth, after daily mechanics; no model calls or new stored fields."""
        self._open_land()
        self._welcome_newcomer()
        self._found_saved_business()
        for building in sorted(self.state.buildings.values(), key=lambda b: b.id):
            if (
                building.cash > 10000
                and building.job_slots > 0
                and self._free_slots(building) == 0
                and building.level < 3
                and building.job_slots <= 18
            ):
                self._upgrade(building, "Busy business reinvests savings", business_pays=True)
        self._house_workers()
        # Persisted Citizen.destitute_days carries the streak, so departures are durable.
        self._let_destitute_leave()
        self._pay_out_surplus()

    def _open_land(self):
        s = self.state
        occupied = {b.plot_id for b in s.buildings.values()}
        if not s.plots or any(
            p.id not in occupied and p.tenant_id is None for p in s.plots.values()
        ):
            return
        positions = {(p.position.x, p.position.z) for p in s.plots.values()}
        # Extend the seed's three-column grid, skipping every existing coordinate.
        index = 0
        for _ in range(2):
            while (4 * (index % 3) - 4, 6 * (index // 3) - 3) in positions:
                index += 1
            position = m.Position(x=4 * (index % 3) - 4, z=6 * (index // 3) - 3)
            pid = f"plot-{s.branch_id}-{s.sequence + 1}"
            s.plots[pid] = m.Plot(id=pid, position=position)
            positions.add((position.x, position.z))
            self.emit("plot_opened", dict(entity_id=pid, position=position.model_dump()))

    def _welcome_newcomer(self):
        s = self.state
        if s.tick % 3 or not s.citizens:
            return
        if sum(c.hunger for c in s.citizens.values()) >= 50 * len(s.citizens):
            return
        opening = next(
            (
                b
                for b in sorted(s.buildings.values(), key=lambda b: b.id)
                if self._free_slots(b) > 0
            ),
            None,
        )
        if opening is None:
            return
        cid = self._spawn(
            m.SpawnCitizenRequest(
                branch_id=s.branch_id,
                expected_sequence=s.sequence,
                name=f"Traveler {s.tick // 3}",
                occupation="Newcomer",
                plot_id=opening.plot_id,
                money=1000,
            )
        )
        self._execute(
            m.ApplyJob(actor_id=cid, building_id=opening.id, rationale="Newcomer seeks an open job")
        )

    def _found_saved_business(self):
        s = self.state
        occupied = {b.plot_id for b in s.buildings.values()}
        plot = next(
            (
                p
                for p in sorted(s.plots.values(), key=lambda p: p.id)
                if p.owner_id is None and p.tenant_id is None and p.id not in occupied
            ),
            None,
        )
        saver = next(
            (c for c in sorted(s.citizens.values(), key=lambda c: c.id) if c.money > 8000), None
        )
        if plot is None or saver is None:
            return
        kinds = ("farm", "bakery", "market")
        kind = min(kinds, key=lambda k: sum(b.kind == k for b in s.buildings.values()))
        self._execute(
            m.FoundBusiness(
                actor_id=saver.id,
                plot_id=plot.id,
                kind=kind,
                capital=MIN_CAPITAL,
                rationale="Saver founds a business",
            )
        )

    def _house_workers(self):
        s = self.state
        occupied = {b.plot_id for b in s.buildings.values()}
        for citizen in sorted(s.citizens.values(), key=lambda c: c.id):
            if citizen.employer_id not in s.buildings or citizen.money <= 2000:
                continue
            if any(
                p.id not in occupied
                and (
                    p.tenant_id == citizen.id or (p.owner_id == citizen.id and p.tenant_id is None)
                )
                for p in s.plots.values()
            ):
                continue
            plot = next(
                (
                    p
                    for p in sorted(s.plots.values(), key=lambda p: p.id)
                    if p.owner_id in s.citizens
                    and p.owner_id != citizen.id
                    and p.tenant_id is None
                    and p.id not in occupied
                    and citizen.money >= p.rent
                ),
                None,
            )
            if plot is not None:
                self._execute(
                    m.LeaseLot(
                        actor_id=citizen.id, plot_id=plot.id, rationale="Worker rents a home"
                    )
                )

    def fork(self, branch_id: str) -> m.WorldState:
        state = self.state.model_copy(deep=True)
        state.branch_id = branch_id
        state.sequence = 0
        return state
