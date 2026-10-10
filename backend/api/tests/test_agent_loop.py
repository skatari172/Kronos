"""The tick loop gathers agent proposals outside the lock and applies them only if still fresh."""

import asyncio

import httpx
from kronos.config import Settings
from kronos.main import create_app
from kronos.service import Service
from kronos_agents.provider import AgentService, MockProvider


class GatedProvider:
    """Answers like the mock, but only after the test opens the gate."""

    def __init__(self):
        self.started, self.gate, self.calls = asyncio.Event(), asyncio.Event(), 0

    async def complete(self, task, observation):
        self.calls += 1
        self.started.set()
        await self.gate.wait()
        return await MockProvider().complete(task, observation)


def _setup(tmp_path):
    """An app wired to a service whose provider blocks; no background clock task."""
    service = Service(Settings(database_url=f"sqlite:///{tmp_path / 'loop.db'}"))
    provider = GatedProvider()
    service.agents = AgentService(provider, timeout=10, round_ticks=1)
    app = create_app()
    app.state.service = service
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return service, provider, client


def _message(sequence, actor="citizen-0", recipient="citizen-1"):
    return {
        "branch_id": "main",
        "expected_sequence": sequence,
        "action": {
            "type": "communicate",
            "actor_id": actor,
            "recipient_id": recipient,
            "message": "Hello while the model thinks",
        },
    }


def test_slow_provider_never_blocks_api_and_stale_manual_tick_is_409(tmp_path):
    async def scenario():
        service, provider, client = _setup(tmp_path)
        async with client:
            tick = asyncio.create_task(
                client.post(
                    "/api/simulation/tick", json={"branch_id": "main", "expected_sequence": 0}
                )
            )
            await asyncio.wait_for(provider.started.wait(), 1)
            # Mid-propose: reads and writes complete promptly instead of waiting on the model.
            read = await asyncio.wait_for(client.get("/api/world"), 1)
            assert read.status_code == 200 and read.json()["tick"] == 0
            write = await asyncio.wait_for(
                client.post("/api/agents/citizen-0/actions", json=_message(0)), 1
            )
            assert write.json()["status"] == "applied"
            assert not tick.done()
            provider.gate.set()
            response = await asyncio.wait_for(tick, 5)
            # The caller's expected_sequence went stale while proposals were gathered.
            assert response.status_code == 409
            assert service.state.tick == 0
        service.store.close()

    asyncio.run(scenario())


def test_manual_tick_applies_fresh_proposals_from_every_scheduled_citizen(tmp_path):
    async def scenario():
        service, provider, client = _setup(tmp_path)
        provider.gate.set()
        async with client:
            response = await client.post(
                "/api/simulation/tick", json={"branch_id": "main", "expected_sequence": 0}
            )
        assert response.status_code == 200
        assert provider.calls == len(service.state.citizens)  # round_ticks=1: everyone
        tagged = [e for e in response.json()["events"] if e["action_id"]]
        assert {e["actor_id"] for e in tagged} == set(service.state.citizens)
        service.store.close()

    asyncio.run(scenario())


def test_clock_drops_stale_proposals_but_still_advances_the_day(tmp_path):
    async def scenario():
        service, provider, client = _setup(tmp_path)
        service.playing = True
        async with client:
            advance = asyncio.create_task(service._advance(service.state.model_copy(deep=True)))
            await asyncio.wait_for(provider.started.wait(), 1)
            write = await asyncio.wait_for(
                client.post("/api/agents/citizen-0/actions", json=_message(0)), 1
            )
            assert write.json()["status"] == "applied"
            provider.gate.set()
            result = await asyncio.wait_for(advance, 5)
        assert result.tick == 1 and service.state.tick == 1
        assert not [e for e in result.events if e.action_id]  # no stale proposal applied
        service.store.close()

    asyncio.run(scenario())


def test_clock_skips_the_day_if_paused_while_proposing(tmp_path):
    async def scenario():
        service, provider, _ = _setup(tmp_path)
        service.playing = True
        advance = asyncio.create_task(service._advance(service.state.model_copy(deep=True)))
        await asyncio.wait_for(provider.started.wait(), 1)
        service.playing = False
        provider.gate.set()
        assert await asyncio.wait_for(advance, 5) is None
        assert service.state.tick == 0
        service.store.close()

    asyncio.run(scenario())


def test_round_length_comes_from_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("KRONOS_AGENT_ROUND_TICKS", "5")
    service = Service(Settings(database_url=f"sqlite:///{tmp_path / 'cfg.db'}"))
    assert service.agents.round_ticks == 5
    service.store.close()
