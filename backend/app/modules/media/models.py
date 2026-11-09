"""``media_assets`` (docs/04 §12, docs/02 §11). Private to the media module."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_check
from app.core.ids import uuid7


class MediaPurpose(StrEnum):
    POST = "post"
    AVATAR = "avatar"
    MESSAGE = "message"
    GROUP_COVER = "group_cover"
    CHALLENGE = "challenge"


class MediaStatus(StrEnum):
    PENDING_UPLOAD = "pending_upload"
    SCANNING = "scanning"
    READY = "ready"
    REJECTED = "rejected"
    DELETED = "deleted"


class RejectionReason(StrEnum):
    MALWARE = "malware"
    POLICY_VIOLATION = "policy_violation"
    TYPE_MISMATCH = "type_mismatch"
    HASH_MISMATCH = "hash_mismatch"
    TOO_LARGE = "too_large"
    PROCESSING_FAILED = "processing_failed"


class MediaAsset(Base):
    __tablename__ = "media_assets"
    __table_args__ = (
        enum_check("purpose", MediaPurpose, "purpose_enum"),
        enum_check("status", MediaStatus, "status_enum"),
        enum_check("rejection_reason", RejectionReason, "rejection_reason_enum"),
        Index("ix_media_assets__owner_created", "owner_id", text("created_at DESC")),
        Index("ix_media_assets__status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending_upload'"))
    mime_type: Mapped[str] = mapped_column(Text)  # declared; verified by magic bytes
    bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(Text)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    alt_text: Mapped[str | None] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    quarantine_key: Mapped[str] = mapped_column(Text)
    # Processed WebP renditions in the public bucket: [{"width", "height", "key"}], largest first.
    variants: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
