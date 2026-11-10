"""Identity module settings (environment / .env)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import AppEnv

# Kept here, not imported from the adapter, so settings never depend on adapters.
FIREBASE_ISSUER_PREFIX = "https://securetoken.google.com/"
FIREBASE_JWKS_URI = (
    "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
)

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

    # Firebase Authentication (ADR-0028). The project ID makes its ID tokens trusted (issuer
    # https://securetoken.google.com/<id>, audience <id>, Google's JWKS) without an OIDC_ISSUERS
    # entry. The Web API key (public, also in the apps) lets the backend look the account up at
    # sign-in: tokens of disabled accounts and tokens revoked by a password change are refused, and
    # a password change ends older sessions (AUTH-005). Required with the project ID outside dev.
    firebase_project_id: str = Field(default="", pattern=r"^([a-z0-9][a-z0-9-]{4,28}[a-z0-9])?$")
    firebase_web_api_key: str = Field(default="", max_length=100)
    # Service account key (JSON) with the Firebase Authentication Admin role: deletes the Firebase
    # account when an account deletion completes (AUTH-010). Shared with the Cloud SQL connector.
    google_service_account_json: SecretStr | None = None

    @property
    def trusted_issuers(self) -> list[TrustedIssuer]:
        """OIDC_ISSUERS plus the Firebase project's issuer when one is configured."""
        issuers = list(self.oidc_issuers)
        if self.firebase_project_id:
            issuers.append(
                TrustedIssuer(
                    issuer=FIREBASE_ISSUER_PREFIX + self.firebase_project_id,
                    audiences=[self.firebase_project_id],
                    jwks_uri=HttpUrl(FIREBASE_JWKS_URI),
                    algorithms=["RS256"],
                )
            )
        return issuers

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
        if not self.oidc_issuers and not self.firebase_project_id:
            raise ValueError(
                "FIREBASE_PROJECT_ID or OIDC_ISSUERS must name at least one identity provider"
            )
        if self.firebase_project_id and not self.firebase_web_api_key:
            raise ValueError("FIREBASE_WEB_API_KEY is required with FIREBASE_PROJECT_ID")
        return self
