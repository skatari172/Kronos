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


def test_round_length_comes_from_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("KRONOS_AGENT_ROUND_TICKS", "5")
    service = Service(Settings(database_url=f"sqlite:///{tmp_path / 'cfg.db'}"))
    assert service.agents.round_ticks == 5
    service.store.close()
