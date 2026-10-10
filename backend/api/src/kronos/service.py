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
    AskResult,
    BranchMetadata,
    DecisionResult,
    InterventionResult,
    MutationRequest,
    SimulationStatus,
    SpawnCitizenRequest,
    SpawnResult,
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
        # Names let the parser resolve "give 5 coins to Ada" to a citizen ID.
        citizens = {cid: c.name for cid, c in self.state.citizens.items()}
        command = await self.agents.parse(body.text, citizens)
        async with self.lock:
            self.check(body)
            result = self.enqueue(command, "player", body.text)
        return InterventionResult(command=command, result=result)

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
