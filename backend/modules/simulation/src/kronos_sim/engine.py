"""Copy-on-write transactions. Only the engine changes live world values."""

import json
import random
from decimal import ROUND_HALF_UP, Decimal

from pydantic import TypeAdapter

from kronos_sim import models as m

EVENT = TypeAdapter(m.SimulationEvent)
ACTION = TypeAdapter(m.AgentAction)
# Action types with engine rules; every other AgentAction is rejected as not_supported.
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
    "research",
    "license_invention",
    "respond_license",
    "adopt_invention",
)
MIN_CAPITAL = 5000  # Cents a founder must move into a new business.
BANKRUPTCY_DAYS = 3  # Consecutive days with a missed wage before a business closes.


class InvalidAction(ValueError):
    """A rule rejection with a stable code for agents and a message for people."""

    def __init__(self, code: m.ActionErrorCode, message: str):
        super().__init__(message)
        self.code = code


def _tuples(value):
    return tuple(_tuples(v) for v in value) if isinstance(value, list) else value


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
        return event

    def result(self, rejected=None) -> m.SimulationTickResult:
        self.state.rng_state = json.loads(json.dumps(self.rng.getstate()))
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
        """Log a rule rejection and remember it, so agents can learn from refused proposals."""
        tx = Engine(self.state)
        tx.action_id = action_id
        actor = tx.state.citizens.get(action.actor_id)
        if actor is None:
            raise error
        actor.memories = (actor.memories + [f"Rejected {action.type}: {error}"])[-8:]
        tx.emit(
            "action_rejected",
            dict(action_type=action.type, code=error.code, message=str(error)),
            actor.id,
            action.rationale,
        )
        return tx.result()

    def _execute(self, action: m.AgentAction):
        s = self.state
        if action.actor_id not in s.citizens:
            raise InvalidAction("unknown_entity", "Unknown citizen")
        actor = s.citizens[action.actor_id]
        building = None
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
            m.AdoptInvention,
        )
        if isinstance(action, owner_only):
            if building.owner_id != actor.id:
                raise InvalidAction("not_owner", "Only the owner may perform this action")

        def emit(kind, payload):
            return self.emit(kind, payload, actor.id, action.rationale)

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
                resource, quantity = "wheat", self.rng.randint(3, 6) * building.level
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
            emit(
                "resource_produced",
                dict(entity_id=building.id, resource=resource, quantity=quantity),
            )
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
            actor.memories = (actor.memories + [f"To {recipient.name}: {action.message}"])[-8:]
            recipient.memories = (recipient.memories + [f"{actor.name}: {action.message}"])[-8:]
            emit("agent_spoke", dict(recipient_id=recipient.id, message=action.message))
            relation = next((r for r in recipient.relationships if r.citizen_id == actor.id), None)
            if relation is None:
                relation = m.Relationship(citizen_id=actor.id)
                recipient.relationships.append(relation)
            relation.trust = min(100, relation.trust + 1)
            emit("relationship_changed", dict(recipient_id=recipient.id, trust=relation.trust))
        elif isinstance(action, m.ConstructBuilding):
            plot = s.plots.get(action.plot_id)
            if plot is None:
                raise InvalidAction("unknown_entity", "Unknown plot")
            if any(b.plot_id == action.plot_id for b in s.buildings.values()):
                raise InvalidAction("lot_occupied", "Construction needs a vacant plot")
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
            )
            emit("building_constructed", dict(entity_id=bid, position=plot.position.model_dump()))
        elif isinstance(action, m.UpgradeBuilding):
            if building.level >= 3:
                raise InvalidAction("bad_params", "Building is already at level 3")
            if actor.money < 2500:
                raise InvalidAction("insufficient_funds", "Upgrade costs 25 coins")
            actor.money -= 2500
            building.level += 1
            emit("building_upgraded", dict(entity_id=building.id, level=building.level))
        elif isinstance(action, m.FoundBusiness):
            plot = s.plots.get(action.plot_id)
            if plot is None:
                raise InvalidAction("unknown_entity", "Unknown plot")
            if any(b.plot_id == plot.id for b in s.buildings.values()):
                raise InvalidAction("lot_occupied", "A business needs a vacant plot")
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
            )
            emit("building_constructed", dict(entity_id=bid, position=plot.position.model_dump()))
            emit(
                "transaction_completed",
                dict(sender_id=actor.id, recipient_id=bid, amount=action.capital),
            )
        elif isinstance(action, m.CloseBusiness):
            self._close(building, actor.id, action.rationale)
        elif isinstance(action, m.SetWage):
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
            staff = [c for c in s.citizens.values() if c.employer_id == building.id]
            if len(staff) >= building.job_slots:
                raise InvalidAction("no_free_slot", "No free job slot")
            worker.employer_id = building.id
            emit("employment_changed", dict(citizen_id=worker.id, building_id=building.id))
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
                if self._researching(actor):
                    raise InvalidAction("bad_params", "Already researching on wage time")
                actor.research_invention_id = invention.id
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
            note = f"{actor.name} offers a {invention.name} license for {action.fee} ({oid})"
            recipient.memories = (recipient.memories + [note])[-8:]
            emit("license_offered", self._offer_payload(offer))
        elif isinstance(action, m.RespondLicense):
            offer = s.license_offers.get(action.offer_id)
            if offer is None:
                raise InvalidAction("unknown_entity", "Unknown or expired license offer")
            if offer.recipient_id != actor.id:
                raise InvalidAction(
                    "insufficient_authority", "Only the recipient may answer this offer"
                )
            if offer.tick != s.tick:
                raise InvalidAction("bad_params", "License offers must be answered the same tick")
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
        else:
            # Schemas are published ahead of their rules; never accept an action as a no-op.
            raise InvalidAction("not_supported", f"Action '{action.type}' is not supported yet")

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
            and self.state.tick <= citizen.research_until_tick
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

    def _innovation_day(self):
        """Expire unanswered license offers, then credit each time researcher's forfeited wage."""
        s = self.state
        for oid in sorted(s.license_offers):
            offer = s.license_offers[oid]
            if offer.tick < s.tick:
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
                citizen.research_until_tick = 0

    def _close(self, building: m.Building, actor_id: str | None, rationale: str | None):
        """Remove a business: cash and goods go to the owner, employees are released."""
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
        for worker in sorted(s.citizens.values(), key=lambda c: c.id):
            if worker.employer_id == building.id:
                worker.employer_id = None
                self.emit(
                    "employment_changed",
                    dict(citizen_id=worker.id, building_id=None, previous_building_id=building.id),
                    actor_id,
                    rationale,
                )
        del s.buildings[building.id]
        self.emit(
            "building_removed",
            dict(entity_id=building.id, position=building.position.model_dump()),
            actor_id,
            rationale,
        )

    def spawn(self, request: m.SpawnCitizenRequest) -> m.SimulationTickResult:
        tx = Engine(self.state)
        plot = tx.state.plots.get(request.plot_id)
        if plot is None:
            raise InvalidAction("unknown_entity", "Unknown plot")
        cid = f"citizen-{tx.state.branch_id}-{tx.state.sequence + 1}"
        tx.state.citizens[cid] = m.Citizen(
            id=cid,
            name=request.name,
            occupation=request.occupation,
            position=m.Position(x=plot.position.x, z=0),
            money=request.money,
            personality=request.personality,
            goal_weights=request.goal_weights,
        )
        position = tx.state.citizens[cid].position.model_dump()
        tx.emit("citizen_spawned", dict(entity_id=cid, position=position))
        return tx.result()

    def intervene(self, command: m.PriceIntervention, text: str) -> m.SimulationTickResult:
        tx = Engine(self.state)
        targets = [b for b in tx.state.buildings.values() if b.kind == "bakery"]
        prices = [
            int(
                (Decimal(b.prices["bread"]) * (100 + command.percent) / 100).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
            for b in targets
        ]
        if not targets or any(p < 1 or p > 1000000 for p in prices):
            raise InvalidAction("bad_params", "No bakery or resulting price out of bounds")
        intervention = tx.emit("intervention_applied", dict(text=text, percent=command.percent))
        for building, price in zip(targets, prices, strict=True):
            old = building.prices["bread"]
            building.prices["bread"] = price
            tx.emit(
                "price_changed",
                dict(building_id=building.id, resource="bread", old_price=old, new_price=price),
                causal_refs=[intervention.id],
            )
        return tx.result()

    def tick(self, proposals: list[m.AgentAction] | None = None) -> m.SimulationTickResult:
        tx = Engine(self.state)
        tx.state.tick += 1
        s = tx.state
        # Business-to-business wheat purchase, then production; no free resource teleportation.
        farms = [b for b in s.buildings.values() if b.kind == "farm"]
        for building in list(s.buildings.values()):
            if building.kind == "bakery" and building.inventory.wheat < 2 and farms:
                farm = farms[0]
                amount = farm.prices["wheat"] * 2
                if farm.inventory.wheat >= 2 and building.cash >= amount:
                    farm.inventory.wheat -= 2
                    building.inventory.wheat += 2
                    farm.cash += amount
                    building.cash -= amount
                    tx.emit(
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
                    tx._execute(m.Produce(actor_id=building.owner_id, building_id=building.id))
                except InvalidAction:
                    pass  # Scarcity is a valid economic outcome.
        missed_payroll = set()
        for citizen in s.citizens.values():
            # Time-mode researchers forfeit today's wage; _innovation_day credits it as progress.
            employer = None if tx._researching(citizen) else s.buildings.get(citizen.employer_id)
            if employer and employer.cash >= employer.wage:
                employer.cash -= employer.wage
                citizen.money += employer.wage
                tx.emit(
                    "transaction_completed",
                    dict(sender_id=employer.id, recipient_id=citizen.id, amount=employer.wage),
                    citizen.id,
                )
            elif employer:
                missed_payroll.add(employer.id)
            citizen.hunger = min(100, citizen.hunger + 20)
            bakeries = sorted(
                (b for b in s.buildings.values() if b.kind == "bakery" and b.inventory.bread),
                key=lambda b: (b.prices["bread"], b.id),
            )
            if citizen.inventory.bread == 0 and bakeries:
                bakery = bakeries[0]
                if citizen.money >= bakery.prices["bread"]:
                    tx._execute(
                        m.Buy(
                            actor_id=citizen.id,
                            building_id=bakery.id,
                            resource="bread",
                            quantity=1,
                            max_unit_price=citizen.money,
                        )
                    )
            if citizen.inventory.bread and citizen.hunger >= 20:
                tx._execute(m.Consume(actor_id=citizen.id))
            tx._execute(m.MoveTo(actor_id=citizen.id, plot_id=tx.rng.choice(sorted(s.plots))))
        for building in sorted(s.buildings.values(), key=lambda b: b.id):
            building.unpaid_days = building.unpaid_days + 1 if building.id in missed_payroll else 0
            if building.unpaid_days >= BANKRUPTCY_DAYS:
                tx._close(building, None, f"Bankrupt: wages unpaid for {BANKRUPTCY_DAYS} days")
        tx._innovation_day()
        tx.state.rng_state = json.loads(json.dumps(tx.rng.getstate()))
        rejected = []
        for proposal in proposals or []:
            # Rejected proposals cannot leak partial mutations or RNG consumption.
            try:
                update = Engine(tx.state).apply(proposal)
                tx.state = update.state
                tx.rng.setstate(_tuples(update.state.rng_state))
                tx.events.extend(update.events)
            except (InvalidAction, ValueError) as exc:
                rejected.append(str(exc))
        return tx.result(rejected)

    def fork(self, branch_id: str) -> m.WorldState:
        state = self.state.model_copy(deep=True)
        state.branch_id = branch_id
        state.sequence = 0
        return state
