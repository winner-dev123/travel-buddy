"""Feed tables. Private to the feed module.

Snapshots live in PostgreSQL rather than Redis so feeds work on every deployment (the serverless
staging API has no Redis); the store is small, keyed by ID and expires after 15 minutes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_check
from app.core.ids import uuid7


class FeedSession(Base):
    """A ranked snapshot of post IDs (<= 500) so pages stay stable (FEED-004)."""

    __tablename__ = "feed_sessions"
    __table_args__ = (Index("ix_feed_sessions__expires_at", "expires_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    post_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid))
    context: Mapped[dict[str, Any]] = mapped_column(JSONB)
    weights_version: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FeedbackKind(StrEnum):
    HIDE = "hide"
    NOT_INTERESTED = "not_interested"
    SEE_LESS_AUTHOR = "see_less_author"


class FeedFeedback(Base):
    """Negative feedback (FEED-007). Retained 180 days (retention job, BL-1.18)."""

    __tablename__ = "feed_feedback"
    __table_args__ = (
        enum_check("kind", FeedbackKind, "kind_enum"),
        Index("ix_feed_feedback__user_created", "user_id", text("created_at DESC")),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    # Author of the post at feedback time (see-less-author penalty without a join).
    author_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
