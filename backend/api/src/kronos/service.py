import asyncio
from uuid import uuid4

from fastapi import HTTPException, WebSocket
from kronos_agents.provider import AgentService, MockProvider, ProviderError
from kronos_history.store import HistoryStore
from kronos_sim.engine import Engine, InvalidAction
from kronos_sim.models import (
    ActionRequest,
    ActionResult,
    ActionValidationResult,
    BranchMetadata,
    MutationRequest,
    SimulationStatus,
    WorldState,
    WorldUpdate,
)
from kronos_sim.seed import initial_world

from kronos.config import Settings


class Service:
    def __init__(self, config: Settings):
        if config.llm_provider != "mock":
            raise ValueError(
                "Only KRONOS_LLM_PROVIDER=mock is bundled; implement LLMProvider to extend"
            )
        self.config = config
        self.store = HistoryStore(config.database_url)
        if self.store.active_id() is None:
            self.store.create(
                initial_world(config.seed), BranchMetadata(id="main", name="Original timeline")
            )
            self.store.activate("main")
        self.state = self.store.world(self.store.active_id())
        self.agents = AgentService(MockProvider(), config.llm_timeout, config.llm_retries)
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
                result = await self.commit(Engine(self.state).apply(body.action))
                status, error = "applied", None
            except InvalidAction as exc:
                result = await self.commit(Engine(self.state).reject(body.action, exc))
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

    async def validate_action(self, body: ActionRequest, citizen_id: str):
        """Run engine checks without changing live state, persistence, or clients."""
        async with self.lock:
            self._evaluate_action(body, citizen_id)
            return ActionValidationResult(
                branch_id=self.state.branch_id, sequence=self.state.sequence, action=body.action
            )

    async def tick(self):
        try:
            proposals = await self.agents.propose(self.state)
        except ProviderError:
            proposals = []  # Failed strategy never prevents routine food/economy mechanics.
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
                if self.playing:
                    try:
                        await self.tick()
                    except Exception as exc:
                        self.playing = False
                        self.error = f"Simulation paused: {type(exc).__name__}"
