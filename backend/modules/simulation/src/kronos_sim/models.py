"""Shared wire contracts. Currency is integer cents; positions are ground-plane x/z."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


class Position(Model):
    x: float
    z: float


class ResourceInventory(Model):
    wheat: int = Field(default=0, ge=0)
    bread: int = Field(default=0, ge=0)


class Relationship(Model):
    citizen_id: str
    trust: int = Field(default=0, ge=-100, le=100)


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
    personality: str = "practical"
    relationships: list[Relationship] = Field(default_factory=list)
    memories: list[str] = Field(default_factory=list)


class Plot(Model):
    id: str
    position: Position


class Building(Model):
    id: str
    name: str
    kind: Literal["farm", "bakery", "market"]
    plot_id: str
    position: Position
    owner_id: str
    cash: int = Field(default=10000, ge=0)
    level: int = Field(default=1, ge=1, le=3)
    inventory: ResourceInventory = Field(default_factory=ResourceInventory)
    prices: dict[str, int] = Field(default_factory=lambda: {"bread": 500, "wheat": 100})


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
    resource: Literal["bread", "wheat"]
    quantity: int = Field(gt=0, le=100)
    max_unit_price: int = Field(gt=0)


class Sell(ActionBase):
    type: Literal["sell"] = "sell"
    building_id: str
    resource: Literal["bread", "wheat"]
    quantity: int = Field(gt=0, le=100)


class TransferMoney(ActionBase):
    type: Literal["transfer_money"] = "transfer_money"
    recipient_id: str
    amount: int = Field(gt=0)


class SetPrice(ActionBase):
    type: Literal["set_price"] = "set_price"
    building_id: str
    resource: Literal["bread", "wheat"]
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
    kind: Literal["farm", "bakery", "market"]


class UpgradeBuilding(ActionBase):
    type: Literal["upgrade_building"] = "upgrade_building"
    building_id: str


class MoveTo(ActionBase):
    type: Literal["move_to"] = "move_to"
    plot_id: str


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
    | MoveTo,
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


class AgentObservation(Model):
    branch_id: str
    tick: int
    sequence: int
    citizen: Citizen
    bread_prices: dict[str, int]


class ActionValidationResult(Model):
    branch_id: str
    sequence: int
    valid: Literal[True] = True
    action: AgentAction
