"""Media storage settings (BL-1.08, docs/02 §11, docs/11)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, HttpUrl, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import AppEnv


class MediaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    app_env: AppEnv = AppEnv.DEVELOPMENT

    # "auto": S3 when credentials are set; otherwise in-process storage in development/test and
    # uploads disabled (503) elsewhere.
    media_storage: Literal["auto", "disabled", "local", "s3"] = "auto"
    # S3-compatible endpoint, e.g. https://<ref>.supabase.co/storage/v1/s3 or an R2/MinIO URL.
    media_s3_endpoint: HttpUrl | None = None
    media_s3_region: str = "us-east-1"
    media_s3_access_key_id: SecretStr | None = None
    media_s3_secret_access_key: SecretStr | None = None
    media_quarantine_bucket: str = Field(default="media-quarantine", pattern=r"^[a-z0-9.-]{3,63}$")
    media_public_bucket: str = Field(default="media-public", pattern=r"^[a-z0-9.-]{3,63}$")
    # Processed private media (message attachments); defaults to the quarantine bucket.
    media_private_bucket: str | None = Field(default=None, pattern=r"^[a-z0-9.-]{3,63}$")
    # Where processed public media is served from (CDN or the bucket's public URL), e.g.
    # https://<ref>.supabase.co/storage/v1/object/public/media-public
    media_public_base_url: HttpUrl | None = None
    # In-process storage only: the API's own base URL, used in upload and media URLs.
    media_local_base_url: str = "http://localhost:8000"
    media_max_pending_uploads: int = Field(default=20, ge=1, le=200)

    @property
    def resolved_storage(self) -> str:
        if self.media_storage != "auto":
            return self.media_storage
        if self.media_s3_access_key_id is not None:
            return "s3"
        return "local" if self.app_env.allows_dev_adapters else "disabled"

    @model_validator(mode="after")
    def _validate(self) -> MediaSettings:
        if self.resolved_storage == "local" and not self.app_env.allows_dev_adapters:
            raise ValueError("MEDIA_STORAGE=local is for development/test only")
        if self.resolved_storage == "s3" and (
            self.media_s3_endpoint is None
            or self.media_s3_access_key_id is None
            or self.media_s3_secret_access_key is None
            or self.media_public_base_url is None
        ):
            raise ValueError(
                "MEDIA_STORAGE=s3 needs MEDIA_S3_ENDPOINT, MEDIA_S3_ACCESS_KEY_ID, "
                "MEDIA_S3_SECRET_ACCESS_KEY and MEDIA_PUBLIC_BASE_URL"
            )
        return self
