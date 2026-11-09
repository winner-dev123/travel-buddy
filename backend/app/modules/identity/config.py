"""Identity module settings (environment / .env)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import AppEnv

_DEV_REFRESH_KEY = "dev-only-refresh-token-derivation-key-change-me"
_MIN_SECRET_LENGTH = 32

IdentityMethod = Literal["email_password", "apple", "google", "oidc", "dev"]


class TrustedIssuer(BaseModel):
    """A production OIDC identity provider whose ID tokens the backend accepts (ADR-0003)."""

    issuer: str = Field(min_length=1)
    audiences: list[str] = Field(min_length=1)
    jwks_uri: HttpUrl
    algorithms: list[Literal["RS256", "ES256", "EdDSA"]] = Field(
        default=["RS256", "ES256", "EdDSA"], min_length=1
    )
    method: IdentityMethod = "oidc"


class IdentitySettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    app_env: AppEnv = AppEnv.DEVELOPMENT

    refresh_token_ttl_days: int = Field(default=60, ge=1, le=365)
    refresh_reuse_leeway_seconds: int = Field(default=30, ge=0, le=120)
    refresh_token_derivation_key: SecretStr = SecretStr(_DEV_REFRESH_KEY)

    minimum_age: int = Field(default=18, ge=13, le=21)
    terms_version: str = Field(default="2026-11-01", max_length=32)
    privacy_version: str = Field(default="2026-11-01", max_length=32)

    # JSON list in env, e.g. OIDC_ISSUERS='[{"issuer": "https://x.auth0.com/", "audiences": ["abc"],
    # "jwks_uri": "https://x.auth0.com/.well-known/jwks.json", "method": "oidc"}]'
    oidc_issuers: list[TrustedIssuer] = Field(default_factory=list)

    # Supabase Auth Admin API key (server-only): deletes the IdP account when an account deletion
    # completes (AUTH-010). Unset = our data is erased but the Supabase Auth user remains.
    supabase_secret_key: SecretStr | None = None

    @model_validator(mode="after")
    def _guard_production(self) -> IdentitySettings:
        if self.app_env.allows_dev_adapters:
            return self
        key = self.refresh_token_derivation_key.get_secret_value()
        if key == _DEV_REFRESH_KEY or len(key) < _MIN_SECRET_LENGTH:
            raise ValueError(
                "REFRESH_TOKEN_DERIVATION_KEY must be a non-default secret of "
                f">= {_MIN_SECRET_LENGTH} chars outside development/test"
            )
        if not self.oidc_issuers:
            raise ValueError("OIDC_ISSUERS must list at least one identity provider")
        return self
