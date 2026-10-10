import pytest
from kronos_agents.provider import AgentService
from kronos_sim.engine import Engine


@pytest.fixture
def route_only(monkeypatch):
    """Isolate route mapping; full mechanics run in test_queue.py and module tests."""

    async def no_proposals(self, world, events=None):
        return []

    monkeypatch.setattr(AgentService, "propose", no_proposals)
    monkeypatch.setattr(Engine, "_automatic_rules", lambda self: None)
    monkeypatch.setattr(Engine, "_growth_rules", lambda self: None)
