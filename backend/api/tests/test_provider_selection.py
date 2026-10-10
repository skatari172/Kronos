import pytest
from kronos.config import Settings
from kronos.service import build_provider
from kronos_agents.provider import MockProvider


def test_mock_is_the_default():
    provider, timeout = build_provider(Settings())
    assert isinstance(provider, MockProvider) and timeout == 3


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="'mock' or 'anthropic'"):
        build_provider(Settings(llm_provider="openai"))


def test_anthropic_without_sdk_or_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY|uv sync --extra anthropic"):
        build_provider(Settings(llm_provider="anthropic"))


def test_anthropic_defaults(monkeypatch):
    pytest.importorskip("anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")  # no request is sent
    provider, timeout = build_provider(Settings(llm_provider="anthropic"))
    assert (provider.model, timeout) == ("claude-opus-5-5", 20)
    monkeypatch.setenv("KRONOS_LLM_TIMEOUT", "8")
    monkeypatch.setenv("KRONOS_LLM_MODEL", "claude-sonnet-5-5")
    provider, timeout = build_provider(Settings(llm_provider="anthropic"))
    assert (provider.model, timeout) == ("claude-sonnet-5-5", 8)
