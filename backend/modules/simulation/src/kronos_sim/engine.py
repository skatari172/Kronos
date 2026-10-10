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
)


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
        if isinstance(action, (m.SetPrice, m.Produce, m.UpgradeBuilding)):
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
        else:
            # Schemas are published ahead of their rules; never accept an action as a no-op.
            raise InvalidAction("not_supported", f"Action '{action.type}' is not supported yet")

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
        for citizen in s.citizens.values():
            employer = s.buildings.get(citizen.employer_id)
            if employer and employer.cash >= 150:
                employer.cash -= 150
                citizen.money += 150
                tx.emit(
                    "transaction_completed",
                    dict(sender_id=employer.id, recipient_id=citizen.id, amount=150),
                    citizen.id,
                )
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
