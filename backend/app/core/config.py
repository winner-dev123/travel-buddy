"""Typed, validated application settings (12-factor; read from environment / .env).

Boot fails fast on invalid configuration. Development-only adapters are rejected outside
development/test environments (threat T-AUTH-08).
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Literal

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
    database_max_overflow: int = Field(default=10, ge=0, le=200)
    database_pool_recycle_seconds: int = Field(default=600, ge=30, le=86400)
    # True when DATABASE_URL points at a transaction-mode pooler (Supabase Supavisor :6543,
    # PgBouncer transaction mode): disables asyncpg prepared-statement caching (ADR-0018).
    database_transaction_pooler: bool = False
    # Empty = Redis not configured (no feature depends on it yet); readiness then skips it.
    redis_url: str = "redis://localhost:6379/0"
    readiness_timeout_seconds: float = Field(default=1.0, gt=0, le=10)

    log_level: str = "INFO"
    log_json: bool = True

    error_type_base_url: str = "https://errors.travelbuddy.app/"
    cors_allowed_origins: list[str] = Field(default_factory=list)

    cursor_signing_key: SecretStr = SecretStr(_DEV_CURSOR_KEY)
    cursor_ttl_seconds: int = Field(default=3600, ge=60, le=86400)

    # Platform access tokens (architecture section 8). Ed25519 private key in PEM (PKCS#8).
    # Outside development/test it is required; in development/test a deterministic,
    # clearly-labelled development key is derived when it is absent.
    platform_jwt_private_key: SecretStr | None = None
    platform_jwt_key_id: str = Field(default="platform-1", min_length=1, max_length=64)
    access_token_ttl_seconds: int = Field(default=900, ge=60, le=3600)

    # Client bootstrap (GET /v1/client-config).
    public_site_url: str = Field(default="http://localhost:3000", pattern=r"^https?://[^\s/]+")
    min_supported_app_version: str = Field(default="0.1.0", pattern=r"^\d+\.\d+\.\d+$")
    latest_app_version: str = Field(default="0.1.0", pattern=r"^\d+\.\d+\.\d+$")
    # Shown in the apps' Help screen and the store listings (App Store 1.5).
    support_email: str = Field(default="support@travelbuddy.app", pattern=r"^[^@\s]+@[^@\s]+$")
    # Public help page; unset until it is published, so no client links to a missing page.
    support_url: str = Field(default="", pattern=r"^(https://[^\s]+)?$")
    # Social sign-in providers enabled in the IdP (Supabase Auth), as a JSON list in env, e.g.
    # AUTH_SOCIAL_PROVIDERS='["apple", "google"]'. The apps show a button per listed provider
    # (AUTH-002, AUTH-003); list one only after configuring it in Supabase.
    auth_social_providers: list[Literal["apple", "google"]] = Field(default_factory=list)

    # JSON object in env, e.g. FEATURE_FLAGS='{"traveler_discovery": true}'.
    # Unknown flag names are rejected at boot by FeatureFlags.
    feature_flags: dict[str, bool] = Field(default_factory=dict)

    # Durable jobs and the outbox relay (BL-1.09, ADR-0004).
    # Shared secret for /internal/jobs/tick; Vercel Cron sends "Authorization: Bearer
    # $CRON_SECRET". Unset = endpoint disabled (404).
    cron_secret: SecretStr | None = None
    # Serverless deployments have no worker: after a response that recorded outbox events, run a
    # short bounded tick (best effort; cron ticks and workers are the safety net).
    jobs_inline_after_response: bool = False
    jobs_inline_budget_seconds: float = Field(default=2.0, gt=0, le=10)
    jobs_tick_budget_seconds: float = Field(default=8.0, gt=0, le=55)

    # Rate limiting (BL-1.15, docs/05 §5). "auto": off in test, in-memory in development, Redis
    # when REDIS_URL is set, otherwise PostgreSQL (serverless deployments without Redis).
    rate_limit_store: Literal["auto", "memory", "redis", "postgres", "disabled"] = "auto"
    # JSON: bucket → "count/seconds[, count/seconds]", e.g. RATE_LIMITS='{"write": "200/60"}'.
    rate_limits: dict[str, str] = Field(default_factory=dict)
    # Use the edge's X-Real-IP / X-Forwarded-For as the client IP. Defaults to true on Vercel, which
    # sets and overwrites both headers.
    trust_proxy_headers: bool | None = None
    running_on_vercel: bool = Field(default=False, validation_alias="VERCEL")
    # Shared with the web BFF, which forwards the browser's IP in X-TB-Client-IP together with this
    # secret in X-TB-Forwarding-Secret (otherwise every web user shares the BFF's egress IP).
    client_ip_forwarding_secret: SecretStr | None = None

    # Realtime gateway (BL-3.04, docs/06, ADR-0023). "auto": Redis fanout when REDIS_URL is set
    # outside development and test, otherwise in-process (a single gateway process).
    realtime_bus: Literal["auto", "memory", "redis"] = "auto"
    realtime_auth_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    realtime_idle_timeout_seconds: float = Field(default=60.0, gt=0, le=600)

    # Push (BL-3.06). "auto": record pushes in memory in development and test (nothing leaves
    # the process), the Expo push service elsewhere. EXPO_ACCESS_TOKEN is optional (enhanced
    # push security in the Expo dashboard).
    push_provider: Literal["auto", "expo", "log", "disabled"] = "auto"
    expo_access_token: SecretStr | None = None
    # Web Push (BL-3.16, NOTIF-005): VAPID private key (base64url scalar or PEM) and contact.
    web_push_vapid_private_key: SecretStr | None = None
    web_push_vapid_subject: str = "mailto:support@travelbuddy.app"

    # Stripe for web purchases (BL-3.14, ADR-0012). Unset: checkout, portal and webhooks give 503.
    # App Store signed data (BL-6.01): the app's bundle id and the pinned SHA-256 fingerprint(s)
    # of Apple Root CA - G3 (comma-separated hex). Both are needed to verify StoreKit 2
    # transactions and App Store Server Notifications; without them Apple answers 503.
    apple_bundle_id: str | None = None
    apple_root_ca_sha256: str | None = None
    # Google Play (BL-6.01): the app's package name and a service account JSON key with access
    # to the Play Developer API verify purchases; RTDN pushes also need the push subscription's
    # OIDC audience (this API's webhook URL) and its service account email. Unset: 503.
    google_play_package_name: str | None = None
    google_play_service_account_json: SecretStr | None = None
    google_pubsub_audience: str | None = None
    google_pubsub_service_account: str | None = None
    stripe_secret_key: SecretStr | None = None
    stripe_webhook_secret: SecretStr | None = None
    stripe_api_base: str = "https://api.stripe.com"

    # AI orchestration (BL-4.02, ADR-0024). "auto": Claude when ANTHROPIC_API_KEY is set, the
    # deterministic fake in development and test, otherwise disabled (503 ai_unavailable).
    ai_provider: Literal["auto", "anthropic", "fake", "disabled"] = "auto"
    anthropic_api_key: SecretStr | None = None
    anthropic_base_url: str | None = None
    ai_itinerary_model: str = "claude-opus-5-5"
    ai_itinerary_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    ai_itinerary_max_tokens: int = Field(default=16000, ge=1024, le=64000)
    ai_timeout_seconds: float = Field(default=180.0, gt=0, le=600)
    ai_translation_model: str = "claude-opus-5-5"
    ai_translation_effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    ai_judge_model: str = "claude-opus-5-5"
    ai_judge_effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    # Server-side refusal fallback (`fallbacks: "default"`, Claude API only; off for proxies).
    ai_refusal_fallback: bool = True
    # Global spend circuit breaker (AI-009): new generations stop once today's spend (UTC) reaches
    # this; 0 stops them all. Provider breaker: that many failures in a row open it (cooldown).
    ai_daily_budget_usd: float = Field(default=25.0, ge=0)
    ai_breaker_failures: int = Field(default=5, ge=1, le=100)
    ai_breaker_cooldown_seconds: float = Field(default=120.0, gt=0, le=3600)

    # Offline packages (BL-4.08): Ed25519 PEM that signs manifests; clients get the public key from
    # GET /v1/client-config. Unset outside development/test: licensing and manifests answer 503.
    offline_manifest_private_key: SecretStr | None = None
    offline_manifest_key_id: str = "offline-1"

    # Development-only adapters (never allowed in staging/production).
    dev_idp_enabled: bool = False
    dev_billing_enabled: bool = False

    @property
    def is_production_like(self) -> bool:
        return not self.app_env.allows_dev_adapters

    @property
    def trusts_proxy_headers(self) -> bool:
        if self.trust_proxy_headers is not None:
            return self.trust_proxy_headers
        return self.running_on_vercel

    @property
    def resolved_rate_limit_store(self) -> str:
        if self.rate_limit_store != "auto":
            return self.rate_limit_store
        if self.app_env is AppEnv.TEST:
            return "disabled"
        if self.app_env is AppEnv.DEVELOPMENT:
            return "memory"
        return "redis" if self.redis_url else "postgres"

    @property
    def resolved_realtime_bus(self) -> str:
        if self.realtime_bus != "auto":
            return self.realtime_bus
        if self.app_env in (AppEnv.TEST, AppEnv.DEVELOPMENT) or not self.redis_url:
            return "memory"
        return "redis"

    @property
    def resolved_push_provider(self) -> str:
        if self.push_provider != "auto":
            return self.push_provider
        return "log" if self.app_env in (AppEnv.TEST, AppEnv.DEVELOPMENT) else "expo"

    @property
    def resolved_ai_provider(self) -> str:
        if self.ai_provider != "auto":
            return self.ai_provider
        if self.anthropic_api_key is not None:
            return "anthropic"
        return "fake" if self.app_env in (AppEnv.TEST, AppEnv.DEVELOPMENT) else "disabled"

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
        if self.ai_provider == "fake":
            problems.append("AI_PROVIDER=fake is only allowed in development/test")
        if self.ai_provider == "anthropic" and self.anthropic_api_key is None:
            problems.append("AI_PROVIDER=anthropic needs ANTHROPIC_API_KEY")
        key = self.cursor_signing_key.get_secret_value()
        if key == _DEV_CURSOR_KEY or len(key) < _MIN_SECRET_LENGTH:
            problems.append(
                f"CURSOR_SIGNING_KEY must be a non-default secret of >= {_MIN_SECRET_LENGTH} chars"
            )
        if self.cron_secret is not None and len(self.cron_secret.get_secret_value()) < (
            _MIN_SECRET_LENGTH
        ):
            problems.append(f"CRON_SECRET must be >= {_MIN_SECRET_LENGTH} chars when set")
        if self.resolved_rate_limit_store in ("memory", "disabled"):
            problems.append(
                "RATE_LIMIT_STORE must be redis or postgres outside development/test (SAFE-005)"
            )
        secret = self.client_ip_forwarding_secret
        if secret is not None and len(secret.get_secret_value()) < _MIN_SECRET_LENGTH:
            problems.append(
                f"CLIENT_IP_FORWARDING_SECRET must be >= {_MIN_SECRET_LENGTH} chars when set"
            )
        if self.platform_jwt_private_key is None:
            problems.append(
                "PLATFORM_JWT_PRIVATE_KEY (Ed25519 PEM) is required outside development/test"
            )
        if problems:
            raise ValueError("; ".join(problems))
        return self

    @model_validator(mode="after")
    def _validate_rate_limits(self) -> Settings:
        from app.core.ratelimit.policy import RatePolicy

        RatePolicy.build(self.rate_limits)  # unknown buckets or malformed limits fail at boot
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
