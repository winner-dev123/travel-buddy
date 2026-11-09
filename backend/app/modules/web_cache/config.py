"""Web cache revalidation settings (environment / .env)."""

from __future__ import annotations

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import AppEnv

_MIN_SECRET_LENGTH = 32


class WebCacheSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    app_env: AppEnv = AppEnv.DEVELOPMENT
    # The web app's receiver (`POST /api/revalidate`). Empty = webhooks disabled.
    web_revalidate_url: str = ""
    # Signing secret (the receiver accepts the current and the previous one during rotation).
    web_revalidate_secret: SecretStr | None = None
    web_revalidate_timeout_seconds: float = Field(default=5.0, gt=0, le=30)

    @property
    def enabled(self) -> bool:
        return bool(self.web_revalidate_url)

    @model_validator(mode="after")
    def _check(self) -> WebCacheSettings:
        if not self.web_revalidate_url:
            return self
        secret = self.web_revalidate_secret
        if secret is None or len(secret.get_secret_value()) < _MIN_SECRET_LENGTH:
            raise ValueError(
                f"WEB_REVALIDATE_SECRET (>= {_MIN_SECRET_LENGTH} chars) is required "
                "when WEB_REVALIDATE_URL is set"
            )
        if not self.app_env.allows_dev_adapters and not self.web_revalidate_url.startswith(
            "https://"
        ):
            raise ValueError("WEB_REVALIDATE_URL must use https outside development/test")
        return self
