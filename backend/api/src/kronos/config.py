from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KRONOS_", env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./backend/database/kronos.db"
    seed: int = 42
    tick_seconds: float = 2
    # Days per simulated year: yearly checkpoints (fork points) fall on these boundaries.
    ticks_per_year: int = Field(30, ge=1)
    llm_provider: str = "mock"
    llm_model: str = "deterministic-v1"
    llm_timeout: float = 3
    llm_retries: int = 1
    # Read from the environment or .env under its standard name (no KRONOS_ prefix).
    anthropic_api_key: SecretStr | None = Field(
        None, validation_alias=AliasChoices("ANTHROPIC_API_KEY", "KRONOS_ANTHROPIC_API_KEY")
    )
    # Every citizen makes one strategic decision per round of this many days (staggered).
    agent_round_ticks: int = Field(3, ge=1)
    # Cost controls for real providers (A5): provider calls per tick (None = no cap) and
    # calls in flight at once. Over the cap, citizens decide with the utility fallback.
    llm_calls_per_tick: int | None = Field(None, ge=0)
    llm_concurrency: int = Field(4, ge=1)
    # Agent tiers: strategic citizens may use the provider; the rest use the fallback.
    # A comma-separated ID list wins; otherwise owners first, then by ID, up to the limit.
    # No limit by default: every citizen is its own agent. Set a number to cap costs.
    strategic_agents: str = ""
    strategic_limit: int | None = Field(None, ge=0)
    # Response cache for real providers (replays and demos cost nothing). Empty disables it;
    # cache_only never calls the provider (a miss falls back to the utility policy).
    llm_cache: str = ".cache/llm"
    llm_cache_only: bool = False
    # Local debug log of every real provider call (JSONL). Empty disables it.
    llm_log: str = ""
