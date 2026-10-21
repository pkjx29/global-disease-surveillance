"""API settings (environment-driven, 12-factor style)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg2://localhost:5432/disease_surveillance"
    cors_origins: str = "http://localhost:5173,http://localhost:8080"
    api_prefix: str = "/api/v1"
    db_pool_size: int = 5
    alert_poll_seconds: float = 2.0
    api_keys: str = ""                    # comma-separated; empty = every protected route returns 401
    rate_limit_per_minute: int = 300      # per API key, per API process

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def api_key_list(self) -> list[str]:
        return [k.strip() for k in self.api_keys.split(",") if k.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
