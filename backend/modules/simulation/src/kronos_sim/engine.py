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
    "gather_resource",
    "apply_job",
    "quit_job",
    "reject_application",
    "lend",
    "respond_loan",
    "repay",
)
MIN_CAPITAL = 5000  # Cents a founder must move into a new business.
BANKRUPTCY_DAYS = 3  # Consecutive days with a missed wage before a business closes.
# Which business kind may draw on each natural stock (farm harvests and worker gathering).
RESOURCE_SOURCES: dict[str, m.BuildingKind] = {"wheat": "farm"}
DEFAULT_TRUST_PENALTY = 30  # Lender trust lost toward a defaulting borrower (spec grudge +0.3).
DEFAULT_REPUTATION_PENALTY = 5  # Borrower reputation lost on default (spec -0.05 on 0..1).


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
        else:
            # Schemas are published ahead of their rules; never accept an action as a no-op.
            raise InvalidAction("not_supported", f"Action '{action.type}' is not supported yet")

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
                if a.citizen_id == citizen_id and a.building_id == building_id
            ),
            None,
        )

    def _free_slots(self, building: m.Building) -> int:
        staff = sum(1 for c in self.state.citizens.values() if c.employer_id == building.id)
        return building.job_slots - staff

    def _resolve(self, application: m.JobApplication, outcome: str, actor_id, rationale):
        """Close one pending application and tell the applicant how it ended."""
        s = self.state
        del s.job_applications[application.id]
        applicant = s.citizens.get(application.citizen_id)
        building = s.buildings.get(application.building_id)
        if applicant is not None and outcome != "withdrawn":
            name = building.name if building else application.building_id
            note = (
                f"Hired by {name}" if outcome == "accepted" else f"{name} rejected my application"
            )
            applicant.memories = (applicant.memories + [note])[-8:]
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
            if other.citizen_id == application.citizen_id:
                self._resolve(other, "withdrawn", None, "Applicant took another job")

    def _resolve_job_applications(self):
        """Daily fallback for applications the owner left unanswered since the last tick.

        First come, first served: an applicant who is still unemployed is hired while the
        business has a free slot and cash for one day's wage; otherwise the application is
        rejected. Applications whose citizen or business is gone, or whose applicant already
        found work, are withdrawn.
        """
        s = self.state
        for application in sorted(s.job_applications.values(), key=lambda a: a.sequence):
            if application.id not in s.job_applications:
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
                    relation = next(
                        (r for r in lender.relationships if r.citizen_id == loan.borrower_id),
                        None,
                    )
                    if relation is None:
                        relation = m.Relationship(citizen_id=loan.borrower_id)
                        lender.relationships.append(relation)
                    relation.trust = max(-100, relation.trust - DEFAULT_TRUST_PENALTY)
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
                        dict(recipient_id=lender.id, trust=trust),
                        loan.borrower_id,
                        causal_refs=[default.id],
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
            employer = s.buildings.get(citizen.employer_id)
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
        tx._regenerate_resources()
        tx._resolve_job_applications()
        tx._settle_loans()
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
