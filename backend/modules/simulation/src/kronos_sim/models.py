"""Shared wire contracts. Currency is integer cents; positions are ground-plane x/z."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


# Widen these together with ResourceInventory when new goods arrive.
TradedResource = Literal["bread", "wheat"]
BuildingKind = Literal["farm", "bakery", "market"]


class Position(Model):
    x: float
    z: float


class ResourceInventory(Model):
    wheat: int = Field(default=0, ge=0)
    bread: int = Field(default=0, ge=0)


class Relationship(Model):
    citizen_id: str
    trust: int = Field(default=0, ge=-100, le=100)


GOALS = ("wealth", "influence", "safety", "reputation")


class GoalWeights(Model):
    """Integer percentages that always sum to 100."""

    wealth: int = Field(default=25, ge=0, le=100)
    influence: int = Field(default=25, ge=0, le=100)
    safety: int = Field(default=25, ge=0, le=100)
    reputation: int = Field(default=25, ge=0, le=100)

    @model_validator(mode="after")
    def _sum(self):
        if sum(getattr(self, goal) for goal in GOALS) != 100:
            raise ValueError("goal weights must sum to 100")
        return self


class GoalWeightChanges(Model):
    """Requested change per goal, in percentage points (spec: at most ±0.1 = ±10)."""

    wealth: int = Field(default=0, ge=-10, le=10)
    influence: int = Field(default=0, ge=-10, le=10)
    safety: int = Field(default=0, ge=-10, le=10)
    reputation: int = Field(default=0, ge=-10, le=10)

    @model_validator(mode="after")
    def _nonzero(self):
        if not any(getattr(self, goal) for goal in GOALS):
            raise ValueError("at least one goal must change")
        return self


class Citizen(Model):
    id: str
    name: str
    occupation: str
    employer_id: str | None = None
    position: Position
    money: int = Field(ge=0)
    hunger: int = Field(default=20, ge=0, le=100)
    inventory: ResourceInventory = Field(default_factory=ResourceInventory)
    goals: list[str] = Field(default_factory=lambda: ["Stay fed", "Save for tomorrow"])
    goal_weights: GoalWeights = Field(default_factory=GoalWeights)
    personality: str = "practical"
    relationships: list[Relationship] = Field(default_factory=list)
    memories: list[str] = Field(default_factory=list)
    reputation: int = Field(
        default=50, ge=0, le=100, description="Public standing; feeds influence"
    )


class Plot(Model):
    id: str
    position: Position


class Building(Model):
    id: str
    name: str
    kind: BuildingKind
    plot_id: str
    position: Position
    owner_id: str
    cash: int = Field(default=10000, ge=0)
    level: int = Field(default=1, ge=1, le=3)
    inventory: ResourceInventory = Field(default_factory=ResourceInventory)
    prices: dict[str, int] = Field(default_factory=lambda: {"bread": 500, "wheat": 100})
    wage: int = Field(default=150, gt=0, le=1000000, description="Paid to each employee per day")
    job_slots: int = Field(default=3, ge=0, le=20)
    unpaid_days: int = Field(
        default=0, ge=0, description="Consecutive days with a missed wage; 3 means bankruptcy"
    )


class WorldState(Model):
    schema_version: Literal[1] = 1
    branch_id: str
    tick: int = 0
    sequence: int = 0
    seed: int
    rng_state: list = Field(default_factory=list)
    citizens: dict[str, Citizen]
    buildings: dict[str, Building]
    plots: dict[str, Plot]


class ActionBase(Model):
    actor_id: str
    rationale: str | None = Field(default=None, max_length=300)


class Buy(ActionBase):
    type: Literal["buy"] = "buy"
    building_id: str
    resource: TradedResource
    quantity: int = Field(gt=0, le=100)
    max_unit_price: int = Field(gt=0)


class Sell(ActionBase):
    type: Literal["sell"] = "sell"
    building_id: str
    resource: TradedResource
    quantity: int = Field(gt=0, le=100)


class TransferMoney(ActionBase):
    type: Literal["transfer_money"] = "transfer_money"
    recipient_id: str
    amount: int = Field(gt=0)


class SetPrice(ActionBase):
    type: Literal["set_price"] = "set_price"
    building_id: str
    resource: TradedResource
    price: int = Field(gt=0, le=1000000)


class Produce(ActionBase):
    type: Literal["produce"] = "produce"
    building_id: str


class Consume(ActionBase):
    type: Literal["consume"] = "consume"


class Communicate(ActionBase):
    type: Literal["communicate"] = "communicate"
    recipient_id: str
    message: str = Field(min_length=1, max_length=200)


class ConstructBuilding(ActionBase):
    type: Literal["construct_building"] = "construct_building"
    plot_id: str
    kind: BuildingKind


class UpgradeBuilding(ActionBase):
    type: Literal["upgrade_building"] = "upgrade_building"
    building_id: str


class MoveTo(ActionBase):
    type: Literal["move_to"] = "move_to"
    plot_id: str


class AdjustGoals(ActionBase):
    """Shift goal weights by bounded deltas; the engine clamps and renormalises to 100."""

    type: Literal["adjust_goals"] = "adjust_goals"
    changes: GoalWeightChanges


class FoundBusiness(ActionBase):
    """Fund a new business from the founder's money; capital becomes business cash."""

    type: Literal["found_business"] = "found_business"
    plot_id: str
    kind: BuildingKind
    capital: int = Field(gt=0)


class CloseBusiness(ActionBase):
    type: Literal["close_business"] = "close_business"
    building_id: str


class SetWage(ActionBase):
    type: Literal["set_wage"] = "set_wage"
    building_id: str
    wage: int = Field(gt=0, le=1000000)


class Hire(ActionBase):
    type: Literal["hire"] = "hire"
    building_id: str
    citizen_id: str


class Fire(ActionBase):
    type: Literal["fire"] = "fire"
    building_id: str
    citizen_id: str


class ApplyJob(ActionBase):
    type: Literal["apply_job"] = "apply_job"
    building_id: str


class QuitJob(ActionBase):
    type: Literal["quit_job"] = "quit_job"


class TradeBundle(Model):
    money: int = Field(default=0, ge=0)
    goods: ResourceInventory = Field(default_factory=ResourceInventory)


class Trade(ActionBase):
    """Offer goods or money to another citizen; the recipient answers with respond_trade."""

    type: Literal["trade"] = "trade"
    recipient_id: str
    give: TradeBundle
    get: TradeBundle


class RespondTrade(ActionBase):
    type: Literal["respond_trade"] = "respond_trade"
    offer_id: str
    accept: bool


class LeaseLot(ActionBase):
    type: Literal["lease_lot"] = "lease_lot"
    plot_id: str


class SetRent(ActionBase):
    """Owner only; the engine limits each change to 20% of the current rent."""

    type: Literal["set_rent"] = "set_rent"
    plot_id: str
    rent: int = Field(ge=0, le=1000000)


class PayRent(ActionBase):
    type: Literal["pay_rent"] = "pay_rent"
    plot_id: str


class Evict(ActionBase):
    type: Literal["evict"] = "evict"
    plot_id: str


class Interact(ActionBase):
    """Bounded relationship change; amount is only used by gift."""

    type: Literal["interact"] = "interact"
    recipient_id: str
    kind: Literal["befriend", "gift", "ally", "argue", "insult", "betray", "mentor"]
    amount: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _gift_amount(self):
        if (self.kind == "gift") != (self.amount is not None):
            raise ValueError("amount is required for gift and not allowed otherwise")
        return self


class Research(ActionBase):
    """Money mode spends amount; time mode forfeits wages for ticks."""

    type: Literal["research"] = "research"
    invention_id: str
    mode: Literal["money", "time"]
    amount: int | None = Field(default=None, gt=0)
    ticks: int | None = Field(default=None, gt=0, le=30)

    @model_validator(mode="after")
    def _mode_fields(self):
        if (self.mode == "money") != (self.amount is not None) or (self.mode == "time") != (
            self.ticks is not None
        ):
            raise ValueError("money mode needs amount only; time mode needs ticks only")
        return self


class LicenseInvention(ActionBase):
    type: Literal["license_invention"] = "license_invention"
    invention_id: str
    recipient_id: str
    fee: int = Field(ge=0)


class AdoptInvention(ActionBase):
    type: Literal["adopt_invention"] = "adopt_invention"
    invention_id: str
    building_id: str


class Lend(ActionBase):
    """Loan offer; rate is basis points per term so money stays integral."""

    type: Literal["lend"] = "lend"
    recipient_id: str
    principal: int = Field(gt=0)
    rate_bps: int = Field(ge=0, le=10000)
    due_tick: int = Field(gt=0)


class Repay(ActionBase):
    type: Literal["repay"] = "repay"
    loan_id: str
    amount: int = Field(gt=0)


class ProposeVote(ActionBase):
    """value is basis points for market_tax and cents for price caps and minimum wage."""

    type: Literal["propose_vote"] = "propose_vote"
    kind: Literal["market_tax", "bread_price_cap", "min_wage"]
    value: int = Field(ge=0, le=1000000)


class CastVote(ActionBase):
    type: Literal["vote"] = "vote"
    vote_id: str
    choice: Literal["yes", "no"]


class GatherResource(ActionBase):
    type: Literal["gather_resource"] = "gather_resource"
    building_id: str
    resource: TradedResource
    quantity: int = Field(gt=0, le=100)


AgentAction = Annotated[
    Buy
    | Sell
    | TransferMoney
    | SetPrice
    | Produce
    | Consume
    | Communicate
    | ConstructBuilding
    | UpgradeBuilding
    | MoveTo
    | AdjustGoals
    | FoundBusiness
    | CloseBusiness
    | SetWage
    | Hire
    | Fire
    | ApplyJob
    | QuitJob
    | Trade
    | RespondTrade
    | LeaseLot
    | SetRent
    | PayRent
    | Evict
    | Interact
    | Research
    | LicenseInvention
    | AdoptInvention
    | Lend
    | Repay
    | ProposeVote
    | CastVote
    | GatherResource,
    Field(discriminator="type"),
]


class EventBase(Model):
    id: str
    branch_id: str
    tick: int
    sequence: int
    actor_id: str | None = None
    rationale: str | None = None
    causal_refs: list[str] = Field(default_factory=list)
    action_id: str | None = None


class PricePayload(Model):
    building_id: str
    resource: str
    old_price: int
    new_price: int


class PriceChanged(EventBase):
    type: Literal["price_changed"] = "price_changed"
    payload: PricePayload


class TransactionPayload(Model):
    sender_id: str
    recipient_id: str
    amount: int
    resource: str | None = None
    quantity: int = 0


class TransactionCompleted(EventBase):
    type: Literal["transaction_completed"] = "transaction_completed"
    payload: TransactionPayload


class ResourcePayload(Model):
    entity_id: str
    resource: str
    quantity: int


class ResourceProduced(EventBase):
    type: Literal["resource_produced"] = "resource_produced"
    payload: ResourcePayload


class ResourceConsumed(EventBase):
    type: Literal["resource_consumed"] = "resource_consumed"
    payload: ResourcePayload


class EntityPayload(Model):
    entity_id: str
    position: Position | None = None
    level: int | None = None


class CitizenMoved(EventBase):
    type: Literal["citizen_moved"] = "citizen_moved"
    payload: EntityPayload


class CitizenSpawned(EventBase):
    type: Literal["citizen_spawned"] = "citizen_spawned"
    payload: EntityPayload


class CitizenRemoved(EventBase):
    type: Literal["citizen_removed"] = "citizen_removed"
    payload: EntityPayload


class BuildingConstructed(EventBase):
    type: Literal["building_constructed"] = "building_constructed"
    payload: EntityPayload


class BuildingUpgraded(EventBase):
    type: Literal["building_upgraded"] = "building_upgraded"
    payload: EntityPayload


class BuildingRemoved(EventBase):
    type: Literal["building_removed"] = "building_removed"
    payload: EntityPayload


class SpeechPayload(Model):
    recipient_id: str
    message: str


class AgentSpoke(EventBase):
    type: Literal["agent_spoke"] = "agent_spoke"
    payload: SpeechPayload


class RelationshipPayload(Model):
    recipient_id: str
    trust: int


class RelationshipChanged(EventBase):
    type: Literal["relationship_changed"] = "relationship_changed"
    payload: RelationshipPayload


ActionErrorCode = Literal[
    "insufficient_authority",
    "insufficient_funds",
    "not_owner",
    "no_free_slot",
    "already_employed",
    "lot_occupied",
    "invention_locked",
    "out_of_stock",
    "trust_too_low",
    "bad_params",
    "rate_limited",
    "unknown_entity",
    "not_supported",
]


class RejectionPayload(Model):
    action_type: str
    code: ActionErrorCode
    message: str


class ActionRejected(EventBase):
    type: Literal["action_rejected"] = "action_rejected"
    payload: RejectionPayload


class GoalsPayload(Model):
    citizen_id: str
    old: GoalWeights
    new: GoalWeights


class GoalsChanged(EventBase):
    type: Literal["goals_changed"] = "goals_changed"
    payload: GoalsPayload


class EmploymentPayload(Model):
    citizen_id: str
    building_id: str | None = Field(description="New employer; null when released")
    previous_building_id: str | None = None


class EmploymentChanged(EventBase):
    type: Literal["employment_changed"] = "employment_changed"
    payload: EmploymentPayload


class WagePayload(Model):
    building_id: str
    old_wage: int
    new_wage: int


class WageChanged(EventBase):
    type: Literal["wage_changed"] = "wage_changed"
    payload: WagePayload


class InterventionPayload(Model):
    text: str
    scope: Literal["all_bakeries"] = "all_bakeries"
    percent: int


class InterventionApplied(EventBase):
    type: Literal["intervention_applied"] = "intervention_applied"
    payload: InterventionPayload


SimulationEvent = Annotated[
    PriceChanged
    | TransactionCompleted
    | ResourceProduced
    | ResourceConsumed
    | CitizenMoved
    | CitizenSpawned
    | CitizenRemoved
    | BuildingConstructed
    | BuildingUpgraded
    | BuildingRemoved
    | AgentSpoke
    | RelationshipChanged
    | ActionRejected
    | GoalsChanged
    | EmploymentChanged
    | WageChanged
    | InterventionApplied,
    Field(discriminator="type"),
]


class WorldUpdate(Model):
    branch_id: str
    tick: int
    sequence: int
    state: WorldState
    events: list[SimulationEvent] = Field(default_factory=list)


class SimulationTickResult(WorldUpdate):
    rejected_actions: list[str] = Field(default_factory=list)


class InterventionRequest(Model):
    text: str = Field(min_length=1, max_length=500)
    branch_id: str
    expected_sequence: int = Field(ge=0)


class PriceIntervention(Model):
    type: Literal["modify_price"] = "modify_price"
    resource: Literal["bread"] = "bread"
    scope: Literal["all_bakeries"] = "all_bakeries"
    percent: int = Field(ge=-90, le=200)


class InterventionResult(Model):
    command: PriceIntervention
    update: WorldUpdate


class SnapshotMetadata(Model):
    id: str
    branch_id: str
    tick: int
    sequence: int
    created_at: str
    integrity_hash: str


class BranchMetadata(Model):
    id: str
    name: str
    parent_branch_id: str | None = None
    source_snapshot_id: str | None = None
    fork_tick: int = 0


class BranchRequest(Model):
    snapshot_id: str
    name: str = Field(min_length=1, max_length=60)


class MutationRequest(Model):
    branch_id: str
    expected_sequence: int = Field(ge=0)


class PlayRequest(MutationRequest):
    speed: Literal[1, 2, 4] = 1


class SimulationStatus(Model):
    playing: bool
    speed: int
    branch_id: str
    error: str | None = None


class ActionRequest(MutationRequest):
    action: AgentAction


Role = Literal["commoner", "business_owner"]
WealthTier = Literal["rich", "middle", "poor"]


class CitizenProfile(Model):
    """A citizen plus values derived from the world (role, tier, employment)."""

    citizen: Citizen
    role: Role
    wealth_tier: WealthTier
    employed: bool
    owned_building_ids: list[str] = Field(default_factory=list)


class AgentObservation(Model):
    """Everything one agent may see: its own state plus public facts, never other citizens."""

    branch_id: str
    tick: int
    sequence: int
    citizen: Citizen
    role: Role
    wealth_tier: WealthTier
    bread_prices: dict[str, int]
    neighbors: dict[str, str] = Field(default_factory=dict, description="Citizen ID to name")
    available_actions: list[str] = Field(default_factory=list)


class ActionValidationResult(Model):
    branch_id: str
    sequence: int
    valid: Literal[True] = True
    action: AgentAction


class ActionResult(Model):
    """Outcome of an agent action. Rule rejections are logged events, not HTTP errors.

    Request problems (stale sequence, unknown citizen, malformed body) still fail with HTTP codes.
    sequence is the world version after this result; send it as the next expected_sequence.
    """

    action_id: str
    branch_id: str
    status: Literal["applied", "rejected"]
    tick: int
    sequence: int
    event_ids: list[str] = Field(default_factory=list)
    error: ActionErrorCode | None = None
    message: str | None = None


class SpawnCitizenRequest(MutationRequest):
    """Setup or intervention only: the starting money enters the economy from outside."""

    name: str = Field(min_length=1, max_length=40)
    occupation: str = Field(min_length=1, max_length=40)
    plot_id: str
    money: int = Field(default=0, ge=0, le=100000)
    personality: str = Field(default="practical", min_length=1, max_length=200)
    goal_weights: GoalWeights = Field(default_factory=GoalWeights)


class SpawnResult(Model):
    citizen_id: str
    update: WorldUpdate


class DecisionResult(Model):
    action: AgentAction
    result: ActionResult


class AskRequest(Model):
    question: str = Field(min_length=1, max_length=300)


class AskResult(Model):
    answer: str = Field(max_length=1000)
    cited_event_ids: list[str] = Field(default_factory=list)


class GoalsUpdateRequest(MutationRequest):
    changes: GoalWeightChanges
    rationale: str | None = Field(default=None, max_length=300)


class BusinessProfile(Model):
    """A building plus values derived from the world. Employees are citizens whose
    employer_id points here; there is no separate employee list to drift out of sync."""

    building: Building
    employee_ids: list[str] = Field(default_factory=list)
    free_slots: int


class BusinessCommand(MutationRequest):
    """Convenience-route body. actor_id is the citizen acting (owner or buyer)."""

    actor_id: str
    rationale: str | None = Field(default=None, max_length=300)


class FoundBusinessRequest(BusinessCommand):
    plot_id: str
    kind: BuildingKind
    capital: int = Field(gt=0)


class WageRequest(BusinessCommand):
    wage: int = Field(gt=0, le=1000000)


class PriceRequest(BusinessCommand):
    resource: TradedResource
    price: int = Field(gt=0, le=1000000)


class EmployeeRequest(BusinessCommand):
    citizen_id: str


class PurchaseRequest(BusinessCommand):
    resource: TradedResource
    quantity: int = Field(gt=0, le=100)
    max_unit_price: int = Field(gt=0)
