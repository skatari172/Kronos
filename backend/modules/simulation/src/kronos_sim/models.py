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


RelationshipType = Literal[
    "acquaintance", "friend", "ally", "rival", "trade", "employer", "creditor", "landlord"
]
InteractionKind = Literal["befriend", "gift", "ally", "argue", "insult", "betray", "mentor"]


class Relationship(Model):
    """How the holding citizen feels about citizen_id (directed; the reverse may differ).

    Spec 0..1 values are scaled by 100: trust 0.7 is 70, grudge 0.5 is 50.
    """

    citizen_id: str
    trust: int = Field(default=0, ge=-100, le=100)
    grudge: int = Field(default=0, ge=0, le=100)
    type: RelationshipType = "acquaintance"
    last_interaction_tick: int | None = Field(
        default=None, ge=0, description="Last tick the holder started an interact toward them"
    )


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
    research_invention_id: str | None = Field(
        default=None, description="Invention this citizen forfeits wages for (time mode)"
    )
    research_start_tick: int = Field(default=0, ge=0)
    research_until_tick: int = Field(
        default=0, ge=0, description="Last day of time-mode research; wages are skipped until then"
    )
    destitute_days: int = Field(
        default=0,
        ge=0,
        description="Consecutive days ending with hunger 100 and no money; 3 means they leave",
    )
    memory_summary: str = Field(
        default="",
        max_length=400,
        description="Rolling digest of routine events and memories older than the 8-line window",
    )
    memory_tally: dict[str, int] = Field(
        default_factory=dict,
        description="Counters behind memory_summary (wages, purchases, meals, folded lines)",
    )


class Plot(Model):
    """A lot. Unowned lots are town land: anyone may build there, nobody collects rent."""

    id: str
    position: Position
    owner_id: str | None = Field(default=None, description="Landlord; null for town land")
    tenant_id: str | None = None
    rent: int = Field(default=0, ge=0, le=1000000, description="Cents per rent period")
    arrears: int = Field(default=0, ge=0, description="Unpaid rent owed by the tenant, in cents")
    missed_periods: int = Field(
        default=0, ge=0, description="Rent periods missed since arrears were last cleared"
    )
    prepaid_periods: int = Field(
        default=0, ge=0, le=4, description="Future rent periods the tenant already paid"
    )


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


# Natural stocks only; this is not a tradeable good list. Widen together with
# engine.RESOURCE_SOURCES when a kind (wood, iron, ...) gains a gathering business.
NaturalResource = Literal["wheat"]


class ResourceStock(Model):
    """A shared natural stock. Farms harvest from it and workers gather from it;
    it regenerates once per tick up to cap. Interventions may edit stock and regen."""

    kind: NaturalResource
    stock: int = Field(ge=0)
    regen_per_tick: int = Field(default=0, ge=0)
    cap: int | None = Field(
        default=None, ge=0, description="Regeneration stops here; null = no cap"
    )


def default_resources() -> dict[str, ResourceStock]:
    """Starting stocks; also used to upgrade worlds saved before resources existed."""
    return {"wheat": ResourceStock(kind="wheat", stock=120, regen_per_tick=6, cap=200)}


JobApplicationStatus = Literal["pending", "hired", "rejected"]


class JobApplication(Model):
    """A request to work at a business. Resolved by the owner or the next daily tick.

    Resolved applications keep their record with status `hired` or `rejected` (a withdrawn
    application counts as rejected); only `pending` ones are open.
    """

    id: str
    citizen_id: str
    building_id: str
    tick: int = Field(ge=0, description="Tick when the citizen applied")
    sequence: int = Field(ge=0, description="World sequence when applied; orders first-come")
    status: JobApplicationStatus = Field(
        default="pending", description="pending until hired or rejected"
    )


LoanStatus = Literal["offered", "active", "repaid", "defaulted", "declined", "expired"]


class Loan(Model):
    """A loan between two citizens. Interest is flat per loan, in integer cents:
    amount_owed = principal + principal * rate_bps // 10000, fixed when the offer is made.

    Lifecycle: offered -> active (borrower accepts; principal moves lender -> borrower) or
    declined. Offers still unanswered on due_tick become expired. An active loan not fully
    repaid once tick > due_tick becomes defaulted (penalties apply once); a defaulted loan can
    still be repaid and then becomes repaid.
    """

    id: str
    lender_id: str
    borrower_id: str
    principal: int = Field(gt=0)
    rate_bps: int = Field(ge=0, le=10000)
    due_tick: int = Field(gt=0)
    amount_owed: int = Field(gt=0)
    amount_repaid: int = Field(default=0, ge=0)
    status: LoanStatus = "offered"
    created_tick: int = Field(default=0, ge=0)


class TradeBundle(Model):
    money: int = Field(default=0, ge=0)
    goods: ResourceInventory = Field(default_factory=ResourceInventory)


class TradeOffer(Model):
    """A pending citizen-to-citizen offer. Resolved offers leave the world; events keep them."""

    id: str
    offerer_id: str
    recipient_id: str
    give: TradeBundle = Field(description="What the offerer hands over on acceptance")
    get: TradeBundle = Field(description="What the offerer receives on acceptance")
    created_tick: int
    expires_tick: int = Field(description="Last tick on which the recipient may accept")
    event_id: str | None = Field(default=None, description="The trade_offered event")
    rationale: str | None = None


class InventionEffect(Model):
    """Production multiplier for adopting buildings, in percent (140 = +40%, 200 = x2)."""

    building_kind: BuildingKind
    resource: TradedResource
    multiplier_pct: int = Field(gt=100, le=1000)


class Invention(Model):
    """Shared research target. Cost and progress are cents; time research counts lost wages."""

    id: str
    name: str
    cost: int = Field(gt=0)
    progress: int = Field(default=0, ge=0)
    contributors: dict[str, int] = Field(
        default_factory=dict, description="Citizen ID to cents contributed"
    )
    unlocked: bool = False
    owner_id: str | None = None
    licensees: list[str] = Field(default_factory=list, description="Citizen IDs")
    adopters: list[str] = Field(default_factory=list, description="Building IDs")
    adoption_cost: int = Field(default=1000, ge=0, description="Paid once from business cash")
    effect: InventionEffect


class LicenseOffer(Model):
    """A pending license; the recipient must accept on the tick it was offered."""

    id: str
    invention_id: str
    owner_id: str
    recipient_id: str
    fee: int = Field(ge=0)
    tick: int


VoteKind = Literal["market_tax", "bread_price_cap", "min_wage"]
VoteChoice = Literal["yes", "no"]


class Policies(Model):
    """Town-vote outcomes in force. 0 means no policy for that kind."""

    market_tax_bps: int = Field(
        default=0, ge=0, le=10000, description="Cut of each buy, shared equally by all citizens"
    )
    bread_price_cap: int = Field(default=0, ge=0, description="Max bread price in cents; 0 = none")
    min_wage: int = Field(default=0, ge=0, description="Min daily wage in cents; 0 = none")


class Vote(Model):
    """A town vote. Tally weights are influence basis points, recorded when the vote closes."""

    id: str
    proposer_id: str
    kind: VoteKind
    value: int = Field(ge=0)
    rationale: str | None = None
    opens_tick: int
    closes_tick: int
    status: Literal["open", "passed", "failed"] = "open"
    ballots: dict[str, VoteChoice] = Field(default_factory=dict, description="Citizen ID to choice")
    yes_weight: int = 0
    no_weight: int = 0


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
    resources: dict[str, ResourceStock] = Field(default_factory=default_resources)
    job_applications: dict[str, JobApplication] = Field(
        default_factory=dict,
        description="Job applications by ID; resolved ones keep their status",
    )

    loans: dict[str, Loan] = Field(default_factory=dict)
    trade_offers: dict[str, TradeOffer] = Field(
        default_factory=dict, description="Pending trade offers by ID"
    )
    inventions: dict[str, Invention] = Field(default_factory=dict)
    license_offers: dict[str, LicenseOffer] = Field(default_factory=dict)
    votes: dict[str, Vote] = Field(default_factory=dict)
    policies: Policies = Field(default_factory=Policies)

    @model_validator(mode="after")
    def _resource_keys(self):
        if any(key != stock.kind for key, stock in self.resources.items()):
            raise ValueError("resources must be keyed by kind")
        return self


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
    kind: InteractionKind
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


class RespondLicense(ActionBase):
    """The license recipient accepts (paying the fee) or declines a same-tick offer."""

    type: Literal["respond_license"] = "respond_license"
    offer_id: str
    accept: bool


class Lend(ActionBase):
    """Loan offer; rate is basis points per term so money stays integral."""

    type: Literal["lend"] = "lend"
    recipient_id: str
    principal: int = Field(gt=0)
    rate_bps: int = Field(ge=0, le=10000)
    due_tick: int = Field(gt=0)


class Repay(ActionBase):
    """Borrower only; partial payments allowed, never more than what is still owed."""

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


class RejectApplication(ActionBase):
    """Owner declines a pending job application; hire accepts one."""

    type: Literal["reject_application"] = "reject_application"
    building_id: str
    citizen_id: str


class RespondLoan(ActionBase):
    """Borrower accepts or declines a loan offer; accepting moves the principal to them."""

    type: Literal["respond_loan"] = "respond_loan"
    loan_id: str
    accept: bool


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
    | GatherResource
    | RejectApplication
    | RespondLoan
    | RespondLicense,
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
    stock_remaining: int | None = Field(
        default=None, description="Shared natural stock left after a farm harvest"
    )


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


class PlotOpened(EventBase):
    type: Literal["plot_opened"] = "plot_opened"
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
    """recipient_id's feeling toward citizen_id, after the change."""

    recipient_id: str
    trust: int
    grudge: int = 0
    type: RelationshipType = "acquaintance"
    citizen_id: str | None = Field(
        default=None, description="Whom the feeling is about; null in older events means actor_id"
    )


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


class GatherPayload(Model):
    citizen_id: str
    building_id: str
    resource: str
    requested: int
    quantity: int = Field(description="Actually moved; less than requested when stock ran low")
    stock_remaining: int


class ResourceGathered(EventBase):
    type: Literal["resource_gathered"] = "resource_gathered"
    payload: GatherPayload


class RegenerationPayload(Model):
    resource: str
    quantity: int
    stock: int


class ResourceRegenerated(EventBase):
    type: Literal["resource_regenerated"] = "resource_regenerated"
    payload: RegenerationPayload


class JobApplicationPayload(Model):
    application_id: str
    citizen_id: str
    building_id: str


class JobApplied(EventBase):
    type: Literal["job_applied"] = "job_applied"
    payload: JobApplicationPayload


class JobApplicationResolvedPayload(JobApplicationPayload):
    outcome: Literal["accepted", "rejected", "withdrawn"]


class JobApplicationResolved(EventBase):
    type: Literal["job_application_resolved"] = "job_application_resolved"
    payload: JobApplicationResolvedPayload


class LoanPayload(Model):
    loan_id: str
    lender_id: str
    borrower_id: str
    status: LoanStatus
    principal: int
    amount_owed: int
    amount_repaid: int
    amount: int = Field(default=0, description="Cents moved by this event (accept or repay)")


class LoanOffered(EventBase):
    type: Literal["loan_offered"] = "loan_offered"
    payload: LoanPayload


class LoanAccepted(EventBase):
    type: Literal["loan_accepted"] = "loan_accepted"
    payload: LoanPayload


class LoanDeclined(EventBase):
    type: Literal["loan_declined"] = "loan_declined"
    payload: LoanPayload


class LoanRepaid(EventBase):
    """Any repayment; payload.status is "repaid" once nothing is owed."""

    type: Literal["loan_repaid"] = "loan_repaid"
    payload: LoanPayload


class LoanExpired(EventBase):
    type: Literal["loan_expired"] = "loan_expired"
    payload: LoanPayload


class LoanDefaultPayload(LoanPayload):
    borrower_reputation: int
    lender_trust: int = Field(description="Lender's trust toward the borrower after the penalty")


class LoanDefaulted(EventBase):
    type: Literal["loan_defaulted"] = "loan_defaulted"
    payload: LoanDefaultPayload


class TradeOfferPayload(Model):
    offer_id: str
    sender_id: str = Field(description="The offerer")
    recipient_id: str
    give: TradeBundle
    get: TradeBundle
    expires_tick: int


class TradeOffered(EventBase):
    type: Literal["trade_offered"] = "trade_offered"
    payload: TradeOfferPayload


class TradeResolutionPayload(Model):
    offer_id: str
    sender_id: str = Field(description="The offerer")
    recipient_id: str


class TradeAccepted(EventBase):
    type: Literal["trade_accepted"] = "trade_accepted"
    payload: TradeResolutionPayload


class TradeDeclined(EventBase):
    type: Literal["trade_declined"] = "trade_declined"
    payload: TradeResolutionPayload


class TradeExpired(EventBase):
    type: Literal["trade_expired"] = "trade_expired"
    payload: TradeResolutionPayload


class ResearchPayload(Model):
    invention_id: str
    citizen_id: str
    mode: Literal["money", "time"]
    amount: int = Field(description="Cents of progress added; 0 when time research starts")
    progress: int
    cost: int
    days_left: int = 0


class ResearchContributed(EventBase):
    type: Literal["research_contributed"] = "research_contributed"
    payload: ResearchPayload


class InventionUnlockedPayload(Model):
    invention_id: str
    owner_id: str
    released_researcher_ids: list[str] = Field(default_factory=list)


class InventionUnlocked(EventBase):
    type: Literal["invention_unlocked"] = "invention_unlocked"
    payload: InventionUnlockedPayload


class LicenseOfferPayload(Model):
    offer_id: str
    invention_id: str
    owner_id: str
    recipient_id: str
    fee: int


class LicenseOffered(EventBase):
    type: Literal["license_offered"] = "license_offered"
    payload: LicenseOfferPayload


class LicenseResolvedPayload(LicenseOfferPayload):
    status: Literal["accepted", "declined", "expired"]


class LicenseResolved(EventBase):
    type: Literal["license_resolved"] = "license_resolved"
    payload: LicenseResolvedPayload


class AdoptionPayload(Model):
    invention_id: str
    building_id: str
    cost: int


class InventionAdopted(EventBase):
    type: Literal["invention_adopted"] = "invention_adopted"
    payload: AdoptionPayload


class VoteProposedPayload(Model):
    vote_id: str
    kind: VoteKind
    value: int
    closes_tick: int


class VoteProposed(EventBase):
    type: Literal["vote_proposed"] = "vote_proposed"
    payload: VoteProposedPayload


class BallotPayload(Model):
    vote_id: str
    choice: VoteChoice
    previous_choice: VoteChoice | None = None


class VoteCast(EventBase):
    type: Literal["vote_cast"] = "vote_cast"
    payload: BallotPayload


class VoteClosedPayload(Model):
    vote_id: str
    kind: VoteKind
    value: int
    passed: bool
    yes_weight: int
    no_weight: int


class VoteClosed(EventBase):
    type: Literal["vote_closed"] = "vote_closed"
    payload: VoteClosedPayload


class PolicyPayload(Model):
    kind: VoteKind
    old_value: int
    new_value: int


class PolicyChanged(EventBase):
    type: Literal["policy_changed"] = "policy_changed"
    payload: PolicyPayload


class TaxPayload(Model):
    building_id: str
    amount: int = Field(description="Total taken from the seller; equals per_citizen * recipients")
    per_citizen: int
    recipient_ids: list[str]


class TaxCollected(EventBase):
    type: Literal["tax_collected"] = "tax_collected"
    payload: TaxPayload


class LotPayload(Model):
    plot_id: str
    owner_id: str | None
    tenant_id: str | None
    rent: int
    arrears: int = 0
    missed_periods: int = 0
    prepaid_periods: int = 0


class LotLeased(EventBase):
    type: Literal["lot_leased"] = "lot_leased"
    payload: LotPayload


class RentChangePayload(Model):
    plot_id: str
    old_rent: int
    new_rent: int


class RentChanged(EventBase):
    type: Literal["rent_changed"] = "rent_changed"
    payload: RentChangePayload


class RentMissed(EventBase):
    """Scheduled collection failed; arrears and missed_periods are the new totals."""

    type: Literal["rent_missed"] = "rent_missed"
    payload: LotPayload


class RentCovered(EventBase):
    """Scheduled collection used one prepaid period; no money moved."""

    type: Literal["rent_covered"] = "rent_covered"
    payload: LotPayload


class TenantEvicted(EventBase):
    """tenant_id is the evicted tenant; arrears are the written-off debt."""

    type: Literal["tenant_evicted"] = "tenant_evicted"
    payload: LotPayload


class InteractionPayload(Model):
    """One interact action. Reputations are after the interaction's side effects."""

    recipient_id: str
    kind: InteractionKind
    amount: int = 0
    actor_reputation: int
    recipient_reputation: int


class CitizenInteracted(EventBase):
    type: Literal["citizen_interacted"] = "citizen_interacted"
    payload: InteractionPayload


class PriceIntervention(Model):
    """Change every bakery's bread price by a percentage."""

    type: Literal["modify_price"] = "modify_price"
    resource: Literal["bread"] = "bread"
    scope: Literal["all_bakeries"] = "all_bakeries"
    percent: int = Field(ge=-90, le=200)


class WageIntervention(Model):
    """Set every business's daily wage, either to `wage` cents or by `percent`."""

    type: Literal["set_wage"] = "set_wage"
    scope: Literal["all_businesses"] = "all_businesses"
    wage: int | None = Field(default=None, gt=0, le=1000000, description="New wage in cents")
    percent: int | None = Field(default=None, ge=-90, le=200, description="Relative change")

    @model_validator(mode="after")
    def _one(self):
        if (self.wage is None) == (self.percent is None):
            raise ValueError("give exactly one of wage or percent")
        return self


class GrantIntervention(Model):
    """Money from outside the economy: positive gives, negative takes (never below zero)."""

    type: Literal["grant_money"] = "grant_money"
    citizen_id: str | None = Field(default=None, description="One citizen; null = everyone")
    amount: int = Field(ge=-1000000, le=1000000, description="Cents per citizen; not zero")

    @model_validator(mode="after")
    def _nonzero(self):
        if self.amount == 0:
            raise ValueError("amount must not be zero")
        return self


class ResourceIntervention(Model):
    """Harvest boom or drought: change a natural stock and/or its daily regrowth."""

    type: Literal["adjust_resource"] = "adjust_resource"
    resource: NaturalResource = "wheat"
    stock_change: int = Field(
        default=0, ge=-10000, le=10000, description="Added to the stock (clamped at zero)"
    )
    regen_per_tick: int | None = Field(
        default=None, ge=0, le=1000, description="New daily regrowth; null keeps it"
    )

    @model_validator(mode="after")
    def _changes(self):
        if not self.stock_change and self.regen_per_tick is None:
            raise ValueError("change the stock or the regrowth")
        return self


class HungerIntervention(Model):
    """Feast (negative change) or famine (positive change); hunger stays within 0..100."""

    type: Literal["adjust_hunger"] = "adjust_hunger"
    citizen_id: str | None = Field(default=None, description="One citizen; null = everyone")
    change: int = Field(ge=-100, le=100, description="Added to hunger; not zero")

    @model_validator(mode="after")
    def _nonzero(self):
        if self.change == 0:
            raise ValueError("change must not be zero")
        return self


class PolicyIntervention(Model):
    """Put a town policy in force directly, without a vote. 0 lifts it."""

    type: Literal["set_policy"] = "set_policy"
    kind: VoteKind
    value: int = Field(ge=0, le=1000000, description="Cents, or basis points for market_tax")

    @model_validator(mode="after")
    def _bounds(self):
        if self.kind == "market_tax" and self.value > 10000:
            raise ValueError("market tax is at most 10000 basis points")
        return self


Intervention = Annotated[
    PriceIntervention
    | WageIntervention
    | GrantIntervention
    | ResourceIntervention
    | HungerIntervention
    | PolicyIntervention,
    Field(discriminator="type"),
]
InterventionKind = Literal[
    "modify_price", "set_wage", "grant_money", "adjust_resource", "adjust_hunger", "set_policy"
]


class InterventionPayload(Model):
    """`kind` names the intervention; `command` is the full parsed command (absent on events
    saved before other kinds existed). `percent` is kept for bread price changes."""

    text: str
    kind: InterventionKind = "modify_price"
    scope: str = "all_bakeries"
    percent: int | None = None
    command: Intervention | None = None
    affected_ids: list[str] = Field(
        default_factory=list, description="Citizens or businesses the intervention changed"
    )


class InterventionApplied(EventBase):
    type: Literal["intervention_applied"] = "intervention_applied"
    payload: InterventionPayload


class TickPayload(Model):
    actions: int = Field(ge=0)


class TickCompleted(EventBase):
    type: Literal["tick_completed"] = "tick_completed"
    payload: TickPayload


SimulationEvent = Annotated[
    PriceChanged
    | TransactionCompleted
    | ResourceProduced
    | ResourceConsumed
    | CitizenMoved
    | CitizenSpawned
    | CitizenRemoved
    | PlotOpened
    | BuildingConstructed
    | BuildingUpgraded
    | BuildingRemoved
    | AgentSpoke
    | RelationshipChanged
    | ActionRejected
    | GoalsChanged
    | EmploymentChanged
    | WageChanged
    | InterventionApplied
    | ResourceGathered
    | ResourceRegenerated
    | JobApplied
    | JobApplicationResolved
    | LoanOffered
    | LoanAccepted
    | LoanDeclined
    | LoanRepaid
    | LoanExpired
    | LoanDefaulted
    | TradeOffered
    | TradeAccepted
    | TradeDeclined
    | TradeExpired
    | ResearchContributed
    | InventionUnlocked
    | LicenseOffered
    | LicenseResolved
    | InventionAdopted
    | VoteProposed
    | VoteCast
    | VoteClosed
    | PolicyChanged
    | TaxCollected
    | LotLeased
    | RentChanged
    | RentMissed
    | RentCovered
    | TenantEvicted
    | CitizenInteracted
    | TickCompleted,
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
    action_results: list["ActionResult"] = Field(default_factory=list)


class InterventionRequest(Model):
    text: str = Field(min_length=1, max_length=500)
    branch_id: str
    expected_sequence: int = Field(ge=0)


class InterventionResult(Model):
    command: Intervention
    result: "ActionResult"


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
    influence: int = Field(default=0, ge=0, le=10000, description="Basis points (0-10000)")


class AgentObservation(Model):
    """Everything one agent may see: its own state plus public facts, never other citizens."""

    branch_id: str
    tick: int
    sequence: int
    citizen: Citizen
    role: Role
    wealth_tier: WealthTier
    bread_prices: dict[str, int]
    bread_stock: dict[str, int] = Field(default_factory=dict)
    neighbors: dict[str, str] = Field(default_factory=dict, description="Citizen ID to name")
    available_actions: list[str] = Field(default_factory=list)
    recent_events: list[SimulationEvent] = Field(default_factory=list)
    loans: list[Loan] = Field(
        default_factory=list,
        description="Open loans (offered, active, defaulted) where this agent lends or borrows",
    )
    incoming_offers: list[TradeOffer] = Field(
        default_factory=list, description="Pending trade offers this citizen may accept or decline"
    )
    ties: list["RelationshipView"] = Field(
        default_factory=list,
        description="Strongest feelings toward others: top few by |trust| or grudge",
    )
    open_jobs: list["JobOpening"] = Field(
        default_factory=list, description="Public job openings (businesses with a free slot)"
    )
    businesses: list["BusinessProfile"] = Field(
        default_factory=list, description="Businesses this citizen owns, with their staff"
    )


class ActionValidationResult(Model):
    branch_id: str
    sequence: int
    valid: Literal[True] = True
    action: AgentAction


class ActionResult(Model):
    """Proposal and session outcome. Queuing does not change the world version.

    scheduled_tick is the earliest execution day; sequence is the last committed world
    version at submission or resolution. Gameplay preconditions are checked at execution.
    """

    action_id: str
    branch_id: str
    status: Literal["queued", "applied", "rejected"]
    action: AgentAction | Intervention
    source: Literal["agent", "player", "backend"] = "agent"
    order: int = Field(ge=1)
    scheduled_tick: int = Field(ge=1)
    text: str | None = None
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


ProposalSource = Literal["llm", "mock", "fallback"]


class DecisionResult(Model):
    action: AgentAction
    result: ActionResult
    source: ProposalSource = Field(
        description="Who chose the action: a real model, the offline mock, or the utility "
        "fallback used when the provider failed. Also prefixed to the rationale, e.g. [fallback]"
    )


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


class GatherRequest(MutationRequest):
    """Convenience-route body; the business is the citizen's current employer."""

    resource: TradedResource
    quantity: int = Field(gt=0, le=100)
    rationale: str | None = Field(default=None, max_length=300)


class InfluenceBreakdown(Model):
    """All components are basis points (0-10000); see queries.influence for the formula."""

    citizen_id: str
    wealth: int = Field(description="Own money plus the cash of businesses owned, in cents")
    wealth_share: int
    reputation: int
    trust_from_others: int
    influence: int


class RolePermission(Model):
    action: str
    scope: Literal["any", "own_business", "own_lot"]
    supported: bool = Field(description="False while the engine still rejects it as not_supported")


class RoleInfo(Model):
    role: Role
    description: str
    permissions: list[RolePermission]


class VoteTally(Model):
    yes_weight: int
    no_weight: int
    yes_share: int = Field(description="Basis points of the weight cast; passes above 5000")
    ballots: int


class VoteView(Model):
    vote: Vote
    tally: VoteTally


class VoteProposalRequest(MutationRequest):
    actor_id: str
    kind: VoteKind
    value: int = Field(ge=0, le=1000000)
    rationale: str | None = Field(default=None, max_length=300)


class LoanCommand(MutationRequest):
    """Loan route body. actor_id is the citizen acting (lender to offer, borrower otherwise)."""

    actor_id: str
    rationale: str | None = Field(default=None, max_length=300)


LotUse = Literal["home", "business", "empty"]


class LotProfile(Model):
    """A lot plus derived use: business if a building stands on it, home if leased without
    one, otherwise empty."""

    lot: Plot
    use: LotUse
    building_id: str | None = None


class LotCommand(MutationRequest):
    """Convenience-route body. actor_id is the citizen acting (tenant or owner)."""

    actor_id: str
    rationale: str | None = Field(default=None, max_length=300)


class JobOpening(Model):
    """A business with at least one free job slot."""

    building_id: str
    name: str
    kind: BuildingKind
    owner_id: str
    plot_id: str
    position: Position
    wage: int
    free_slots: int
    applicant_ids: list[str] = Field(default_factory=list, description="Pending applicants")


class ApplyJobRequest(MutationRequest):
    business_id: str
    rationale: str | None = Field(default=None, max_length=300)


class QuitJobRequest(MutationRequest):
    rationale: str | None = Field(default=None, max_length=300)


class LoanOfferRequest(LoanCommand):
    borrower_id: str
    principal: int = Field(gt=0)
    rate_bps: int = Field(ge=0, le=10000)
    due_tick: int = Field(gt=0)


class LoanResponseRequest(LoanCommand):
    accept: bool


class ResearchRequest(BusinessCommand):
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


class LicenseRequest(BusinessCommand):
    recipient_id: str
    fee: int = Field(ge=0)


class LicenseResponseRequest(BusinessCommand):
    accept: bool


class LoanRepayRequest(LoanCommand):
    amount: int = Field(gt=0)


class MarketPrice(Model):
    """One good across every building that lists a price for it. Cents; average rounds half up."""

    resource: str
    average: int
    min: int
    max: int
    sellers: int


class MarketPrices(Model):
    branch_id: str
    tick: int
    sequence: int
    prices: list[MarketPrice] = Field(default_factory=list)


class PricePoint(Model):
    """The market price after the event at this sequence (the branch start for the first)."""

    tick: int
    sequence: int
    average: int
    min: int
    max: int
    sellers: int


class PriceHistory(Model):
    branch_id: str
    resource: str
    points: list[PricePoint] = Field(default_factory=list)


class AgentOffers(Model):
    citizen_id: str
    incoming: list[TradeOffer] = Field(default_factory=list)
    outgoing: list[TradeOffer] = Field(default_factory=list)


class TradeRequest(BusinessCommand):
    """actor_id is the offerer."""

    recipient_id: str
    give: TradeBundle
    get: TradeBundle


class RespondTradeRequest(BusinessCommand):
    """actor_id must be the offer's recipient."""

    accept: bool


class AdoptRequest(BusinessCommand):
    building_id: str


class BallotRequest(MutationRequest):
    actor_id: str
    choice: VoteChoice
    rationale: str | None = Field(default=None, max_length=300)


class RentRequest(LotCommand):
    rent: int = Field(ge=0, le=1000000)


class RelationshipView(Model):
    """One directed tie with the other citizen's name; known is false when no entry exists."""

    citizen_id: str
    name: str
    trust: int = 0
    grudge: int = 0
    type: RelationshipType = "acquaintance"
    last_interaction_tick: int | None = None
    known: bool = True


class RelationshipPair(Model):
    """Both directions of one tie: a_to_b is a's feeling toward b."""

    a_id: str
    b_id: str
    a_to_b: RelationshipView
    b_to_a: RelationshipView


class InteractRequest(MutationRequest):
    target_id: str
    kind: InteractionKind
    amount: int | None = Field(default=None, gt=0, description="Cents; required for gift only")
    rationale: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _gift_amount(self):
        if (self.kind == "gift") != (self.amount is not None):
            raise ValueError("amount is required for gift and not allowed otherwise")
        return self


AgentObservation.model_rebuild()

SimulationTickResult.model_rebuild()
InterventionResult.model_rebuild()
