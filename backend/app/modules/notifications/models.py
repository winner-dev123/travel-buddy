"""Notification table (docs/04 §12). Private to the notifications module."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_check
from app.core.ids import uuid7


class NotificationType(StrEnum):
    CONNECTION_REQUEST = "connection_request"
    CONNECTION_ACCEPTED = "connection_accepted"
    NEW_MESSAGE = "new_message"
    GROUP_INVITATION = "group_invitation"
    GROUP_ANNOUNCEMENT = "group_announcement"
    CHALLENGE_STARTED = "challenge_started"
    CHALLENGE_RESULT = "challenge_result"
    POST_REACTION = "post_reaction"
    POST_COMMENT = "post_comment"
    NEW_FOLLOWER = "new_follower"
    FOLLOW_REQUEST = "follow_request"
    MODERATION_NOTICE = "moderation_notice"
    SUBSCRIPTION_NOTICE = "subscription_notice"
    AI_GENERATION_READY = "ai_generation_ready"
    DATA_EXPORT_READY = "data_export_ready"


class Notification(Base):
    """``id`` is a UUIDv7, so it orders notifications by creation (the list cursor)."""

    __tablename__ = "notifications"
    __table_args__ = (
        enum_check("type", NotificationType, "type_enum"),
        Index("ix_notifications__user_id_id", "user_id", text("id DESC")),
        Index("ix_notifications__unread", "user_id", postgresql_where=text("read_at IS NULL")),
        # Event delivery is at-least-once: one notification per (recipient, dedupe key).
        Index("uq_notifications__user_id_dedupe_key", "user_id", "dedupe_key", unique=True),
        Index("ix_notifications__created_at", "created_at"),  # retention (90 days)
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    entity_type: Mapped[str | None] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # Render data only (IDs, codes); never message bodies or location (NOTIF-004).
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    dedupe_key: Mapped[str] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
