import os

import pytest
from kronos.config import Settings


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch):
    """Tests never read the developer's .env or shell settings, so a local
    KRONOS_LLM_PROVIDER=anthropic (and its key) can never trigger a paid call."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in list(os.environ):
        if name.startswith("KRONOS_") or name == "ANTHROPIC_API_KEY":
            monkeypatch.delenv(name)
