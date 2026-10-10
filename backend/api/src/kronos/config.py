from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KRONOS_", env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./kronos.db"
    seed: int = 42
    tick_seconds: float = 2
    llm_provider: str = "mock"
    llm_model: str = "deterministic-v1"
    llm_timeout: float = 3
    llm_retries: int = 1
