"""Typed, validated application settings (12-factor; read from environment / .env).

Boot fails fast on invalid configuration. Development-only adapters are rejected outside
development/test environments (threat T-AUTH-08).
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_CURSOR_KEY = "dev-only-cursor-signing-key-change-me"
_MIN_SECRET_LENGTH = 32


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def allows_dev_adapters(self) -> bool:
        return self in (AppEnv.DEVELOPMENT, AppEnv.TEST)


class Settings(BaseSettings):
    """Process-wide settings. Module-specific settings live in their own module."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    app_env: AppEnv = AppEnv.DEVELOPMENT
    service_name: str = "travelbuddy-api"
    service_version: str = "0.1.0"

    database_url: str = "postgresql+asyncpg://travelbuddy:travelbuddy@localhost:5432/travelbuddy"
    database_pool_size: int = Field(default=10, ge=1, le=200)
    redis_url: str = "redis://localhost:6379/0"
    readiness_timeout_seconds: float = Field(default=1.0, gt=0, le=10)

    log_level: str = "INFO"
    log_json: bool = True

    error_type_base_url: str = "https://errors.travelbuddy.app/"
    cors_allowed_origins: list[str] = Field(default_factory=list)

    cursor_signing_key: SecretStr = SecretStr(_DEV_CURSOR_KEY)
    cursor_ttl_seconds: int = Field(default=3600, ge=60, le=86400)

    # JSON object in env, e.g. FEATURE_FLAGS='{"traveler_discovery": true}'.
    # Unknown flag names are rejected at boot by FeatureFlags.
    feature_flags: dict[str, bool] = Field(default_factory=dict)

    # Development-only adapters (never allowed in staging/production).
    dev_idp_enabled: bool = False
    dev_billing_enabled: bool = False

    @property
    def is_production_like(self) -> bool:
        return not self.app_env.allows_dev_adapters

    @property
    def expose_api_docs(self) -> bool:
        return self.app_env.allows_dev_adapters

    @model_validator(mode="after")
    def _guard_production(self) -> Settings:
        if self.app_env.allows_dev_adapters:
            return self
        problems: list[str] = []
        if self.dev_idp_enabled:
            problems.append("DEV_IDP_ENABLED must be false outside development/test")
        if self.dev_billing_enabled:
            problems.append("DEV_BILLING_ENABLED must be false outside development/test")
        key = self.cursor_signing_key.get_secret_value()
        if key == _DEV_CURSOR_KEY or len(key) < _MIN_SECRET_LENGTH:
            problems.append(
                f"CURSOR_SIGNING_KEY must be a non-default secret of >= {_MIN_SECRET_LENGTH} chars"
            )
        if problems:
            raise ValueError("; ".join(problems))
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
