import os

import pytest
from kronos.config import Settings
from kronos_agents.provider import AgentService
from kronos_sim.engine import Engine


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch):
    """Tests never read the developer's .env or shell settings, so a local
    KRONOS_LLM_PROVIDER=anthropic (and its key) can never trigger a paid call."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in list(os.environ):
        if name.startswith("KRONOS_") or name == "ANTHROPIC_API_KEY":
            monkeypatch.delenv(name)


@pytest.fixture
def route_only(monkeypatch):
    """Isolate route mapping; full mechanics run in test_queue.py and module tests."""

    async def no_proposals(self, world, events=None):
        return []

    monkeypatch.setattr(AgentService, "propose", no_proposals)
    monkeypatch.setattr(Engine, "_automatic_rules", lambda self: None)
    monkeypatch.setattr(Engine, "_growth_rules", lambda self: None)
