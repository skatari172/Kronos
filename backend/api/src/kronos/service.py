import asyncio
import hashlib
import logging
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, WebSocket
from kronos_agents.fallback import UtilityPolicy
from kronos_agents.middleware import CachingProvider, LoggingProvider
from kronos_agents.provider import AgentService, LLMProvider, MockProvider, ProviderError
from kronos_history.store import HistoryStore
from kronos_sim.engine import Engine, InvalidAction
from kronos_sim.models import (
    ActionRequest,
    ActionResult,
    ActionValidationResult,
    AgentAction,
    AskResult,
    BranchMetadata,
    CloseBusiness,
    DecisionResult,
    DeterminedToolCall,
    Evict,
    Fire,
    FoundBusiness,
    GatherResource,
    GrantIntervention,
    Hire,
    HungerIntervention,
    InterventionResult,
    LeaseLot,
    MutationRequest,
    PolicyIntervention,
    PriceIntervention,
    ProposeVote,
    ResourceIntervention,
    SetPrice,
    SetRent,
    SetWage,
    SimulationStatus,
    SpawnCitizenRequest,
    SpawnResult,
    ToolParameters,
    UpgradeBuilding,
    UserQueryRequest,
    UserQueryResult,
    WageIntervention,
    WorldState,
    WorldUpdate,
)
from kronos_sim.queries import observe
from kronos_sim.seed import initial_world

from kronos.config import Settings

logger = logging.getLogger(__name__)


def prompt_version() -> str:
    """Short hash of the prompt templates, so cached replies expire when prompts change."""
    from kronos_agents import prompts

    return hashlib.sha256(Path(prompts.__file__).read_bytes()).hexdigest()[:12]


def _wrap(provider: LLMProvider, config: Settings, tag: str) -> LLMProvider:
    """Debug log innermost (real calls only), response cache outermost."""
    if config.llm_log:
        provider = LoggingProvider(provider, config.llm_log)
    if config.llm_cache:
        provider = CachingProvider(
            provider, config.llm_cache, tag=tag, replay_only=config.llm_cache_only
        )
    return provider


def build_provider(config: Settings) -> tuple[LLMProvider, float]:
    """Pick the provider from KRONOS_LLM_PROVIDER. `mock` (default) needs no key or network."""
    if config.llm_provider == "mock":
        return MockProvider(), config.llm_timeout
    if config.llm_provider == "anthropic":
        from kronos_agents.anthropic_provider import (
            DEFAULT_MODEL,
            DEFAULT_TIMEOUT,
            AnthropicProvider,
        )

        # The 3 s default is tuned for the mock; a real model gets 20 s unless set explicitly.
        timeout = (
            config.llm_timeout if "llm_timeout" in config.model_fields_set else DEFAULT_TIMEOUT
        )
        model = DEFAULT_MODEL if config.llm_model == "deterministic-v1" else config.llm_model
        try:
            if timeout < DEFAULT_TIMEOUT / 2:
                logger.warning(
                    "KRONOS_LLM_TIMEOUT=%s s is short for Claude; unset it to use %s s",
                    timeout,
                    DEFAULT_TIMEOUT,
                )
            key = config.anthropic_api_key
            provider = AnthropicProvider(
                model, timeout=timeout, api_key=key.get_secret_value() if key else None
            )
            return _wrap(provider, config, tag=f"{model}:{prompt_version()}"), timeout
        except ProviderError as exc:
            raise ValueError(str(exc)) from exc
    raise ValueError(
        f"Unknown KRONOS_LLM_PROVIDER={config.llm_provider!r}; expected 'mock' or 'anthropic'"
    )


class Service:
    def __init__(self, config: Settings):
        provider, timeout = build_provider(config)  # fail fast, before touching storage
        self.config = config
        self.store = HistoryStore(config.database_url)
        if self.store.active_id() is None:
            self.store.create(
                initial_world(config.seed), BranchMetadata(id="main", name="Original timeline")
            )
            self.store.activate("main")
        self.state = self.store.world(self.store.active_id())
        strategic = [c.strip() for c in config.strategic_agents.split(",") if c.strip()]
        self.agents = AgentService(
            provider,
            timeout,
            config.llm_retries,
            round_ticks=config.agent_round_ticks,
            fallback=UtilityPolicy(),  # A failed provider call falls back, never stalls.
            calls_per_tick=config.llm_calls_per_tick,
            concurrency=config.llm_concurrency,
            strategic_ids=strategic or None,
            strategic_limit=config.strategic_limit,
        )
        self.lock = asyncio.Lock()
        self.branch_epoch = 0
        # V1 attempts live only in this API session; committed Events are durable history.
        self.actions: dict[str, ActionResult] = {}
        self.action_order = 0
        self.action_session = uuid4().hex
        self.decision_task: asyncio.Task | None = None
        self.clients: set[WebSocket] = set()
        self.playing = False
        self.speed = 1
        self.error: str | None = None

    def status(self) -> SimulationStatus:
        return SimulationStatus(
            playing=self.playing, speed=self.speed, branch_id=self.state.branch_id, error=self.error
        )

    def check(self, request: MutationRequest):
        if (request.branch_id, request.expected_sequence) != (
            self.state.branch_id,
            self.state.sequence,
        ):
            raise HTTPException(409, "World changed. Resynchronize and try again.")

    def update(self, state: WorldState | None = None) -> WorldUpdate:
        state = state if state is not None else self.state
        return WorldUpdate(
            branch_id=state.branch_id,
            tick=state.tick,
            sequence=state.sequence,
            state=state,
            events=self.store.list_events(state.branch_id, state.sequence),
        )

    async def broadcast(self, update: WorldUpdate):
        # Always send the documented world envelope, even when the engine returns a tick result.
        payload = WorldUpdate(
            branch_id=update.branch_id,
            tick=update.tick,
            sequence=update.sequence,
            state=update.state,
            events=update.events,
        ).model_dump(mode="json")

        async def send(client):
            try:
                await asyncio.wait_for(client.send_json(payload), timeout=0.5)
            except Exception:
                self.clients.discard(client)
                try:
                    await client.close()
                except Exception:
                    pass

        await asyncio.gather(*(send(client) for client in tuple(self.clients)))

    async def commit(self, result):
        # Persist through the unchanged world/event interface, without an action ledger.
        persisted = WorldUpdate(
            branch_id=result.branch_id,
            tick=result.tick,
            sequence=result.sequence,
            state=result.state,
            events=result.events,
        )
        self.store.commit(persisted, self.state.sequence)
        self.state = result.state
        for outcome in getattr(result, "action_results", []):
            self.actions[outcome.action_id] = outcome
        await self.broadcast(result)
        return result

    def enqueue(self, action, source="agent", text=None) -> ActionResult:
        """Caller holds the lock. Runtime attempts never change persisted world state."""
        self.action_order += 1
        record = ActionResult(
            action_id=f"action-{self.state.branch_id}:{self.action_session}:{self.action_order:08d}",
            branch_id=self.state.branch_id,
            status="queued",
            action=action.model_copy(deep=True),
            source=source,
            order=self.action_order,
            scheduled_tick=self.state.tick + 1,
            text=text,
            tick=self.state.tick,
            sequence=self.state.sequence,
        )
        self.actions[record.action_id] = record
        return record.model_copy(deep=True)

    def pending(self) -> list[ActionResult]:
        return [
            record.model_copy(deep=True)
            for record in self.actions.values()
            if record.branch_id == self.state.branch_id and record.status == "queued"
        ]

    def _authorize(self, body: ActionRequest, citizen_id: str | None):
        """Caller holds the lock. Request-level checks; failures are HTTP errors, never logged."""
        self.check(body)
        if citizen_id is not None:
            if citizen_id not in self.state.citizens:
                raise KeyError("Unknown citizen")
            if body.action.actor_id != citizen_id:
                raise InvalidAction(
                    "insufficient_authority",
                    "Proposal actor_id must match the citizen_id in the route",
                )

    def _evaluate_action(self, body: ActionRequest, citizen_id: str | None = None):
        """Caller holds the lock. Evaluate a proposal against a copied world."""
        self._authorize(body, citizen_id)
        return Engine(self.state).apply(body.action)

    async def execute_action(
        self, body: ActionRequest, citizen_id: str | None = None, source="player"
    ) -> ActionResult:
        """Admit a proposal. Only a later tick may change gameplay state."""
        async with self.lock:
            self._authorize(body, citizen_id)
            return self.enqueue(body.action, source)

    async def submit_agent_action(self, body: ActionRequest, citizen_id: str) -> ActionResult:
        return await self.execute_action(body, citizen_id, source="agent")

    def action_result(self, action_id: str) -> ActionResult:
        if action_id in self.actions:
            return self.actions[action_id].model_copy(deep=True)
        raise KeyError("Unknown action in this API session; read committed Events for history")

    async def intervene(self, body):
        """Like `decide`: check the request against the current world, parse outside the
        lock (a real model can take longer than a tick), then queue it unless the branch
        changed meanwhile. Queued interventions run on the next tick either way."""
        async with self.lock:
            self.check(body)
            # Names let the parser resolve "give 5 coins to Ada" to a citizen ID.
            citizens = {cid: c.name for cid, c in self.state.citizens.items()}
            branch, epoch = self.state.branch_id, self.branch_epoch
        command = await self.agents.parse(body.text, citizens)
        async with self.lock:
            if self.branch_epoch != epoch or self.state.branch_id != branch:
                raise HTTPException(409, "Active branch changed while reading the command")
            result = self.enqueue(command, "player", body.text)
        return InterventionResult(command=command, result=result)

    def _check_query_concurrency(self, body: UserQueryRequest) -> None:
        if body.branch_id is not None and body.branch_id != self.state.branch_id:
            raise HTTPException(409, "World changed. Resynchronize and try again.")
        if body.expected_sequence is not None and body.expected_sequence != self.state.sequence:
            raise HTTPException(409, "World changed. Resynchronize and try again.")

    def _build_user_query_context(self) -> dict:
        state = self.state
        return {
            "tick": state.tick,
            "citizen_names": {cid: c.name for cid, c in sorted(state.citizens.items())},
            "citizens": {
                cid: {
                    "name": c.name,
                    "occupation": c.occupation,
                    "money": c.money,
                    "hunger": c.hunger,
                }
                for cid, c in sorted(state.citizens.items())
            },
            "buildings": {
                bid: {
                    "name": b.name,
                    "kind": b.kind,
                    "owner_id": b.owner_id,
                    "plot_id": b.plot_id,
                    "wage": b.wage,
                    "prices": b.prices,
                }
                for bid, b in sorted(state.buildings.items())
            },
            "plots": {
                pid: {
                    "owner_id": p.owner_id,
                    "tenant_id": p.tenant_id,
                    "rent": p.rent,
                }
                for pid, p in sorted(state.plots.items())
            },
            "resources": {r: res.stock for r, res in sorted(state.resources.items())},
            "policies": {
                pol: val for pol, val in sorted(state.policies.model_dump().items()) if val
            },
        }

    def _build_agent_action_from_params(self, tool: str, params: ToolParameters) -> AgentAction:
        actor_id = params.actor_id
        if actor_id is None:
            if params.building_id and params.building_id in self.state.buildings:
                actor_id = self.state.buildings[params.building_id].owner_id
            elif (
                params.plot_id
                and params.plot_id in self.state.plots
                and self.state.plots[params.plot_id].owner_id
            ):
                actor_id = self.state.plots[params.plot_id].owner_id
            elif self.state.citizens:
                actor_id = next(iter(sorted(self.state.citizens.keys())))
            else:
                actor_id = "citizen-1"

        if tool == "found_business":
            return FoundBusiness(
                actor_id=actor_id,
                plot_id=params.plot_id or "plot-1",
                kind=params.kind or "farm",  # type: ignore[arg-type]
                capital=params.capital or 5000,
                rationale="Found business via player query",
            )
        if tool == "set_price":
            return SetPrice(
                actor_id=actor_id,
                building_id=params.building_id or "bakery",
                resource=params.resource or "bread",
                price=params.price or 500,
                rationale="Set price via player query",
            )
        if tool == "set_wage":
            return SetWage(
                actor_id=actor_id,
                building_id=params.building_id or "farm",
                wage=params.wage or 150,
                rationale="Set wage via player query",
            )
        if tool == "hire":
            return Hire(
                actor_id=actor_id,
                building_id=params.building_id or "farm",
                citizen_id=params.citizen_id or actor_id,
                rationale="Hire citizen via player query",
            )
        if tool == "fire":
            return Fire(
                actor_id=actor_id,
                building_id=params.building_id or "farm",
                citizen_id=params.citizen_id or actor_id,
                rationale="Fire citizen via player query",
            )
        if tool == "close_business":
            return CloseBusiness(
                actor_id=actor_id,
                building_id=params.building_id or "farm",
                rationale="Close business via player query",
            )
        if tool == "upgrade_building":
            return UpgradeBuilding(
                actor_id=actor_id,
                building_id=params.building_id or "bakery",
                rationale="Upgrade building via player query",
            )
        if tool == "gather_resource":
            return GatherResource(
                actor_id=actor_id,
                building_id=params.building_id or "farm",
                resource=params.resource or "wheat",
                quantity=params.quantity or 10,
                rationale="Gather resource via player query",
            )
        if tool == "lease_lot":
            return LeaseLot(
                actor_id=actor_id,
                plot_id=params.plot_id or "plot-1",
                rationale="Lease lot via player query",
            )
        if tool == "set_rent":
            return SetRent(
                actor_id=actor_id,
                plot_id=params.plot_id or "plot-1",
                rent=params.rent or 200,
                rationale="Set rent via player query",
            )
        if tool == "evict":
            return Evict(
                actor_id=actor_id,
                plot_id=params.plot_id or "plot-1",
                rationale="Evict tenant via player query",
            )
        if tool == "propose_vote":
            return ProposeVote(
                actor_id=actor_id,
                kind=params.kind or "min_wage",  # type: ignore[arg-type]
                value=params.value or 200,
                rationale="Propose vote via player query",
            )
        raise ValueError(f"Unknown action tool: {tool}")

    async def _execute_determined_tool(
        self, query: str, tool_call: DeterminedToolCall, body: UserQueryRequest
    ) -> UserQueryResult:
        params = tool_call.parameters
        endpoint = tool_call.endpoint
        tool = tool_call.tool

        # 1. Interventions (/api/interventions)
        if endpoint == "/api/interventions" or tool in (
            "modify_price",
            "set_wage_intervention",
            "grant_money",
            "adjust_resource",
            "adjust_hunger",
            "set_policy",
        ):
            cmd = None
            if tool == "modify_price":
                cmd = PriceIntervention(
                    percent=params.percent if params.percent is not None else 10,
                )
            elif tool in ("set_wage", "set_wage_intervention"):
                if params.wage is not None:
                    cmd = WageIntervention(wage=params.wage)
                else:
                    cmd = WageIntervention(
                        percent=params.percent if params.percent is not None else 10
                    )
            elif tool == "grant_money":
                amt = params.amount if params.amount not in (None, 0) else 100
                cmd = GrantIntervention(
                    amount=amt,
                    citizen_id=params.citizen_id,
                )
            elif tool == "adjust_resource":
                sc = params.stock_change or 0
                if sc == 0 and params.regen_per_tick is None:
                    sc = 50
                cmd = ResourceIntervention(
                    resource="wheat",
                    stock_change=sc,
                    regen_per_tick=params.regen_per_tick,
                )
            elif tool == "adjust_hunger":
                ch = params.change if params.change not in (None, 0) else -30
                cmd = HungerIntervention(
                    change=ch,
                    citizen_id=params.citizen_id,
                )
            elif tool == "set_policy":
                cmd = PolicyIntervention(
                    kind=params.kind or "min_wage",  # type: ignore[arg-type]
                    value=params.value or 0,
                )
            if cmd is not None:
                async with self.lock:
                    self._check_query_concurrency(body)
                    action_res = self.enqueue(cmd, "player", query)
                return UserQueryResult(
                    query=query,
                    tool_call=tool_call,
                    status="queued",
                    result=action_res.model_dump(mode="json"),
                    scheduled_tick=action_res.scheduled_tick,
                    action_id=action_res.action_id,
                )

        # 2. Spawning Citizens (/api/agents or tool == "spawn_citizen")
        if endpoint == "/api/agents" or tool == "spawn_citizen":
            plot_id = params.plot_id
            if not plot_id:
                plot_id = next(iter(sorted(self.state.plots.keys())), "plot-0")
            spawn_req = SpawnCitizenRequest(
                branch_id=self.state.branch_id,
                expected_sequence=self.state.sequence,
                name=params.name or "New Citizen",
                occupation=params.occupation or "unemployed",
                money=params.money if params.money is not None else 1000,
                plot_id=plot_id,
                personality=params.occupation or "practical",
            )
            spawn_res = await self.spawn(spawn_req)
            return UserQueryResult(
                query=query,
                tool_call=tool_call,
                status="applied",
                result=spawn_res.model_dump(mode="json"),
            )

        # 3. Simulation Controls: Tick (/api/simulation/tick or tool == "simulation_tick")
        if endpoint == "/api/simulation/tick" or tool == "simulation_tick":
            mut_req = None
            if body.branch_id is not None and body.expected_sequence is not None:
                mut_req = MutationRequest(
                    branch_id=body.branch_id,
                    expected_sequence=body.expected_sequence,
                )
            tick_res = await self.tick(mut_req)
            return UserQueryResult(
                query=query,
                tool_call=tool_call,
                status="applied",
                result=tick_res.model_dump(mode="json"),
            )

        # 4. Simulation Playback (/api/simulation/play or /api/simulation/pause)
        if (
            endpoint in ("/api/simulation/play", "/api/simulation/pause")
            or tool == "simulation_playback"
        ):
            is_playing = (
                params.playing
                if params.playing is not None
                else (endpoint == "/api/simulation/play")
            )
            async with self.lock:
                self._check_query_concurrency(body)
                self.playing = is_playing
                if is_playing and params.speed:
                    self.speed = params.speed
                status_res = self.status()
            return UserQueryResult(
                query=query,
                tool_call=tool_call,
                status="applied",
                result=status_res.model_dump(mode="json"),
            )

        # 5. Citizen / Business Actions (/api/actions)
        if endpoint == "/api/actions":
            action_obj = self._build_agent_action_from_params(tool, params)
            action_req = ActionRequest(
                branch_id=self.state.branch_id,
                expected_sequence=self.state.sequence,
                action=action_obj,
            )
            action_res = await self.execute_action(action_req, source="player")
            return UserQueryResult(
                query=query,
                tool_call=tool_call,
                status="queued",
                result=action_res.model_dump(mode="json"),
                scheduled_tick=action_res.scheduled_tick,
                action_id=action_res.action_id,
            )

        raise ValueError(f"Unsupported tool or endpoint: {endpoint} {tool}")

    async def handle_user_query(self, body: UserQueryRequest) -> UserQueryResult:
        self._check_query_concurrency(body)
        async with self.lock:
            context = self._build_user_query_context()
        tool_call = await self.agents.resolve_user_query(body.query, context)
        try:
            return await self._execute_determined_tool(body.query, tool_call, body)
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Failed executing determined tool %s: %s", tool_call.tool, exc)
            return UserQueryResult(
                query=body.query,
                tool_call=tool_call,
                status="rejected",
                error=str(exc),
            )

    async def decide(self, citizen_id: str, request: MutationRequest) -> DecisionResult:
        """Ask the provider for one action, then submit it like any other agent action.

        The provider call happens outside the lock. If the world moves on meanwhile,
        the proposal is queued for the next available tick and validated against current state.
        """
        async with self.lock:
            self.check(request)
            observation = observe(
                self.state,
                citizen_id,
                self.store.list_citizen_events(
                    self.state.branch_id, citizen_id, self.state.sequence, limit=8
                ),
            )
            epoch = self.branch_epoch
        action, source = await self.agents.proposal(observation)
        async with self.lock:
            if self.branch_epoch != epoch or self.state.branch_id != observation.branch_id:
                raise HTTPException(409, "Active branch changed during deliberation")
            if action.actor_id not in self.state.citizens:
                raise KeyError("Unknown citizen")
            result = self.enqueue(action, "agent")
        return DecisionResult(action=action, result=result, source=source)

    async def ask(self, citizen_id: str, question: str) -> AskResult:
        """Read-only grounded Q&A over the citizen's own events on the active branch."""
        async with self.lock:
            observation = observe(
                self.state,
                citizen_id,
                self.store.list_citizen_events(
                    self.state.branch_id, citizen_id, self.state.sequence, limit=8
                ),
            )
        events = self.store.list_citizen_events(
            observation.branch_id, citizen_id, observation.sequence, limit=20
        )
        return await self.agents.ask(question, observation, events)

    async def spawn(self, request: SpawnCitizenRequest) -> SpawnResult:
        async with self.lock:
            self.check(request)
            result = await self.commit(Engine(self.state).spawn(request))
            return SpawnResult(citizen_id=result.events[0].payload.entity_id, update=result)

    async def validate_action(self, body: ActionRequest, citizen_id: str):
        """Run engine checks without changing live state, persistence, or clients."""
        async with self.lock:
            self._evaluate_action(body, citizen_id)
            return ActionValidationResult(
                branch_id=self.state.branch_id, sequence=self.state.sequence, action=body.action
            )

    async def tick(self, request: MutationRequest | None = None):
        async with self.lock:
            if request is not None:
                self.check(request)
            batch = self.pending()
            result = await self.commit(Engine(self.state).tick(queued=batch))
            snapshot, epoch = self.state.model_copy(deep=True), self.branch_epoch
        # Keep the single clock moving while at most one bounded decision batch awaits I/O.
        if self.decision_task is None or self.decision_task.done():
            self.decision_task = asyncio.create_task(
                self._deliberate(snapshot, epoch, result.events)
            )
        return result

    async def _deliberate(self, snapshot, epoch, events):
        try:
            proposals = await self.agents.propose(snapshot, events)
            async with self.lock:
                if epoch == self.branch_epoch and snapshot.branch_id == self.state.branch_id:
                    for action in proposals:
                        if action.actor_id in self.state.citizens:
                            self.enqueue(action, "agent")
        except ProviderError:
            pass  # A failed strategy never interrupts deterministic daily mechanics.
        except Exception as exc:
            self.error = f"Agent decisions skipped: {type(exc).__name__}"

    async def stop_decisions(self):
        if self.decision_task is not None:
            self.decision_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.decision_task

    async def fork(self, snapshot_id: str, name: str):
        original = self.store.restore(snapshot_id)
        branch_id = str(uuid4())
        state = Engine(original).fork(branch_id)
        meta = BranchMetadata(
            id=branch_id,
            name=name,
            parent_branch_id=original.branch_id,
            source_snapshot_id=snapshot_id,
            fork_tick=state.tick,
        )
        self.store.create(state, meta)
        return meta

    async def loop(self):
        while True:
            await asyncio.sleep(max(0.1, self.config.tick_seconds / self.speed))
            if self.playing:
                try:
                    await self.tick()
                except Exception as exc:
                    self.playing = False
                    self.error = f"Simulation paused: {type(exc).__name__}"
