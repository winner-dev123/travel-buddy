"""Media API shapes (contract ``CreateMediaUploadRequest``, ``MediaUpload``, ``MediaAsset``,
``MediaRef``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Purpose = Literal["post", "avatar", "message", "group_cover", "challenge"]
MimeType = Literal[
    "image/jpeg", "image/png", "image/webp", "image/heic", "video/mp4", "video/quicktime"
]


class CreateMediaUploadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: Purpose
    mime_type: MimeType
    bytes: int = Field(ge=1, le=524_288_000)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    width: int | None = Field(default=None, ge=1, le=20_000)
    height: int | None = Field(default=None, ge=1, le=20_000)
    duration_ms: int | None = Field(default=None, ge=1, le=180_000)
    alt_text: str | None = Field(default=None, max_length=300)


class _Response(BaseModel):
    model_config = ConfigDict(frozen=True)


class UploadTarget(_Response):
    method: Literal["PUT"] = "PUT"
    url: str
    headers: dict[str, str]
    expires_at: datetime


class MediaUpload(_Response):
    media_id: uuid.UUID
    upload: UploadTarget
    max_bytes: int


class MediaRef(_Response):
    id: uuid.UUID
    kind: Literal["image", "video", "audio"]
    status: Literal["ready", "processing", "unavailable"]
    url: str | None
    url_expires_at: datetime | None = None
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    alt_text: str | None = None
    blurhash: str | None = None
    attribution: None = None


class MediaAssetOut(_Response):
    id: uuid.UUID
    purpose: Purpose
    status: Literal["pending_upload", "scanning", "ready", "rejected", "deleted"]
    mime_type: str
    bytes: int
    width: int | None
    height: int | None
    duration_ms: int | None
    rejection_reason: str | None
    ref: MediaRef | None
    created_at: datetime
