import asyncio
import hashlib
import logging
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
        self.store.commit(result, self.state.sequence)
        self.state = result.state
        await self.broadcast(result)
        return result

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

    async def execute_action(self, body: ActionRequest, citizen_id: str | None = None):
        """One serialized execution path for user, agent, and backend action tools."""
        async with self.lock:
            result = self._evaluate_action(body, citizen_id)
            return await self.commit(result)

    async def submit_agent_action(self, body: ActionRequest, citizen_id: str) -> ActionResult:
        """Like execute_action, but a rule rejection is committed as an action_rejected event."""
        async with self.lock:
            self._authorize(body, citizen_id)
            action_id = f"action-{self.state.branch_id}:{self.state.sequence}"
            try:
                result = await self.commit(Engine(self.state).apply(body.action, action_id))
                status, error = "applied", None
            except InvalidAction as exc:
                result = await self.commit(Engine(self.state).reject(body.action, exc, action_id))
                status, error = "rejected", exc
            return ActionResult(
                action_id=action_id,
                branch_id=result.branch_id,
                status=status,
                tick=result.tick,
                sequence=result.sequence,
                event_ids=[event.id for event in result.events],
                error=error.code if error else None,
                message=str(error) if error else None,
            )

    def action_result(self, action_id: str) -> ActionResult:
        """Rebuild an agent action's outcome from the events tagged with its ID."""
        try:
            branch_id, before = action_id.removeprefix("action-").rsplit(":", 1)
            after = int(before)
        except ValueError:
            raise KeyError("Unknown action") from None
        tagged = []
        for event in self.store.list_events_after(branch_id, after, limit=50):
            if event.action_id != action_id:
                break
            tagged.append(event)
        if not tagged:
            raise KeyError("Unknown action")
        rejection = next((e for e in tagged if e.type == "action_rejected"), None)
        return ActionResult(
            action_id=action_id,
            branch_id=branch_id,
            status="rejected" if rejection else "applied",
            tick=tagged[0].tick,
            sequence=tagged[-1].sequence,
            event_ids=[event.id for event in tagged],
            error=rejection.payload.code if rejection else None,
            message=rejection.payload.message if rejection else None,
        )

    async def decide(self, citizen_id: str, request: MutationRequest) -> DecisionResult:
        """Ask the provider for one action, then submit it like any other agent action.

        The provider call happens outside the lock; if the world moves on meanwhile, the
        submission fails the version check (409) instead of applying a stale decision.
        """
        async with self.lock:
            self.check(request)
            observation = observe(self.state, citizen_id)
        action, source = await self.agents.proposal(observation)
        body = ActionRequest(
            branch_id=observation.branch_id,
            expected_sequence=observation.sequence,
            action=action,
        )
        return DecisionResult(
            action=action, result=await self.submit_agent_action(body, citizen_id), source=source
        )

    async def ask(self, citizen_id: str, question: str) -> AskResult:
        """Read-only grounded Q&A over the citizen's own events on the active branch."""
        async with self.lock:
            observation = observe(self.state, citizen_id)
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
        """Advance one day. Agent proposals are gathered outside the lock (see `_advance`).

        With a `request` (the manual tick route) the caller's version is checked before and
        after the provider calls, so a world that moved on meanwhile is a 409, like `/decide`.
        """
        async with self.lock:
            if request is not None:
                self.check(request)
            world = self.state.model_copy(deep=True)
        return await self._advance(world, request)

    async def _advance(self, world: WorldState, request: MutationRequest | None = None):
        """Gather proposals for `world` (a private copy) without the lock, then apply them.

        A slow provider never blocks other API calls. If the world changed meanwhile (any
        commit, seek or branch switch moves `branch_id`/`sequence`), the stale proposals are
        dropped: the clock still advances the day with no proposals (when it is still
        playing), and the citizens whose slot it was wait for their next round.
        """
        try:
            proposals = await self.agents.propose(world)
        except ProviderError:
            proposals = []  # Failed strategy never prevents routine food/economy mechanics.
        async with self.lock:
            if request is not None:
                self.check(request)
            elif not self.playing:
                return None  # Paused (or the branch switched) while proposals were gathered.
            if (world.branch_id, world.sequence) != (self.state.branch_id, self.state.sequence):
                proposals = []
            return await self.commit(Engine(self.state).tick(proposals))

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
            async with self.lock:
                if not self.playing:
                    continue
                world = self.state.model_copy(deep=True)
            try:
                await self._advance(world)
            except Exception as exc:
                self.playing = False
                self.error = f"Simulation paused: {type(exc).__name__}"
