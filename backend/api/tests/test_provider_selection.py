import pytest
from kronos.config import Settings
from kronos.service import build_provider
from kronos_agents.middleware import CachingProvider, LoggingProvider
from kronos_agents.provider import MockProvider


def test_mock_is_the_default():
    provider, timeout = build_provider(Settings())
    assert isinstance(provider, MockProvider) and timeout == 3


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="'anthropic' or 'gemini'"):
        build_provider(Settings(llm_provider="openai"))


def test_anthropic_without_sdk_or_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY|uv sync --extra anthropic"):
        build_provider(Settings(llm_provider="anthropic"))


def test_anthropic_defaults(monkeypatch):
    pytest.importorskip("anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-real")  # no request is sent
    provider, timeout = build_provider(Settings(llm_provider="anthropic", llm_cache=""))
    assert (provider.model, timeout) == ("claude-haiku-5-5", 20)
    monkeypatch.setenv("KRONOS_LLM_TIMEOUT", "8")
    monkeypatch.setenv("KRONOS_LLM_MODEL", "claude-sonnet-5-5")
    provider, timeout = build_provider(Settings(llm_provider="anthropic", llm_cache=""))
    assert (provider.model, timeout) == ("claude-sonnet-5-5", 8)


def test_anthropic_key_is_read_from_settings():
    pytest.importorskip("anthropic")
    config = Settings(llm_provider="anthropic", llm_cache="", anthropic_api_key="sk-ant-x")
    provider, _ = build_provider(config)
    assert provider.client.api_key == "sk-ant-x"


def test_real_providers_are_cached_and_logged(tmp_path):
    pytest.importorskip("anthropic")
    config = Settings(
        llm_provider="anthropic",
        anthropic_api_key="sk-ant-x",
        llm_cache=str(tmp_path / "cache"),
        llm_cache_only=True,
        llm_log=str(tmp_path / "llm.jsonl"),
    )
    provider, _ = build_provider(config)
    assert isinstance(provider, CachingProvider) and provider.replay_only
    assert isinstance(provider.inner, LoggingProvider)
    assert provider.tag.startswith("claude-haiku-5-5:")
    # The mock is free and deterministic, so it is never wrapped.
    assert isinstance(build_provider(Settings())[0], MockProvider)
