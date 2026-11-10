"""``ai_generations`` (docs/04 §10): one row per AI request, private to this module.

Telemetry columns (tokens, cost, latency, model, prompt version, validation result) are kept for
13 months; quotas count this month's ``pending`` and ``succeeded`` rows. The raw prompt and the raw
model response are never stored. ``params`` (the typed request) lives only until the generation
finishes, and ``result`` (the validated proposal the owner polls for) for 30 days.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_check
from app.core.ids import uuid7

FEATURES = (
    "itinerary_generate",
    "trip_replan",
    "assistant_chat",
    "challenge_judge",
    "post_translate",
)
STATUSES = (
    "pending",
    "succeeded",
    "validation_failed",
    "provider_error",
    "refused",
    "quota_exceeded",
    "unavailable",
)


class AIGeneration(Base):
    __tablename__ = "ai_generations"
    __table_args__ = (
        enum_check("feature", FEATURES, "feature_enum"),
        enum_check("status", STATUSES, "status_enum"),
        Index("ix_ai_generations__user_feature", "user_id", "feature", text("created_at DESC")),
        Index("ix_ai_generations__created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    feature: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    locale: Mapped[str] = mapped_column(Text, server_default=text("'en'"))
    input_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    cache_read_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    cache_write_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    cost_micros: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    error_code: Mapped[str | None] = mapped_column(Text)
    validation_errors: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    params: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(Text)
    provider_request_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PostTranslation(Base):
    """Cached machine translation of a post into one language (POST-010). Reused while the post's
    text is unchanged (``body_hash``); the original is never replaced."""

    __tablename__ = "post_translations"

    post_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
    target_language: Mapped[str] = mapped_column(Text, primary_key=True)
    source_language: Mapped[str] = mapped_column(Text)
    body_hash: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
