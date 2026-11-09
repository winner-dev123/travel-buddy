"""Trust and safety tables (docs/04 section 5). Private to the trust_safety module."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
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


class UserBlock(Base):
    """``blocker`` blocked ``blocked``. Effects are bidirectional (SAFE-001)."""

    __tablename__ = "user_blocks"
    __table_args__ = (
        CheckConstraint("blocker_id <> blocked_id", name="not_self"),
        Index("ix_user_blocks__blocked", "blocked_id"),
    )

    blocker_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    blocked_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReportStatus(StrEnum):
    OPEN = "open"
    IN_REVIEW = "in_review"
    ACTIONED = "actioned"
    DISMISSED = "dismissed"


class ReportReason(StrEnum):
    SPAM = "spam"
    HARASSMENT = "harassment"
    HATE = "hate"
    SEXUAL_CONTENT = "sexual_content"
    MINOR_SAFETY = "minor_safety"
    VIOLENCE = "violence"
    SELF_HARM = "self_harm"
    SCAM = "scam"
    PRIVACY_VIOLATION = "privacy_violation"
    IMPERSONATION = "impersonation"
    ILLEGAL = "illegal"
    OTHER = "other"


class ReportTargetType(StrEnum):
    POST = "post"
    COMMENT = "comment"
    USER = "user"
    MESSAGE = "message"
    GROUP = "group"
    CHALLENGE = "challenge"
    MEDIA = "media"


class ContentReport(Base):
    """A user report with an evidence snapshot (SAFE-002); queue ordered by priority (SAFE-003)."""

    __tablename__ = "content_reports"
    __table_args__ = (
        enum_check("status", ReportStatus, "status_enum"),
        enum_check("reason", ReportReason, "reason_enum"),
        enum_check("target_type", ReportTargetType, "target_type_enum"),
        Index("ix_content_reports__queue", "status", text("priority DESC"), "created_at"),
        Index("ix_content_reports__target", "target_type", "target_id"),
        Index("ix_content_reports__target_author", "target_author_id"),
        Index(
            "uq_content_reports__open_per_reporter",
            "reporter_id",
            "target_type",
            "target_id",
            unique=True,
            postgresql_where=text("status IN ('open', 'in_review')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    reporter_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    target_type: Mapped[str] = mapped_column(Text)
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    target_author_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reason: Mapped[str] = mapped_column(Text)
    details: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(Text, server_default=text("'open'"))
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModerationActionType(StrEnum):
    REMOVE_CONTENT = "remove_content"
    RESTORE_CONTENT = "restore_content"
    LIMIT_VISIBILITY = "limit_visibility"
    WARN = "warn"
    RESTRICT = "restrict"
    SUSPEND = "suspend"
    BAN = "ban"
    REINSTATE = "reinstate"
    REMOVE_MEMBER = "remove_member"


class RestrictionKind(StrEnum):
    """What a ``restrict`` action limits (SAFE-013)."""

    POSTING_LIMITED = "posting_limited"
    COMMENTING_LIMITED = "commenting_limited"
    MESSAGING_LIMITED = "messaging_limited"
    CONNECTION_REQUESTS_LIMITED = "connection_requests_limited"
    DISCOVERY_DISABLED = "discovery_disabled"
    MEDIA_UPLOAD_LIMITED = "media_upload_limited"


class ModerationAction(Base):
    """Every enforcement decision, platform- or group-scoped (ADM-002)."""

    __tablename__ = "moderation_actions"
    __table_args__ = (
        enum_check("action", ModerationActionType, "action_enum"),
        enum_check("target_type", ReportTargetType, "target_type_enum"),
        CheckConstraint("scope IN ('platform', 'group')", name="scope_enum"),
        enum_check("restriction_kind", RestrictionKind, "restriction_kind_enum"),
        CheckConstraint(
            "(action = 'restrict') = (restriction_kind IS NOT NULL)",
            name="restriction_kind_required",
        ),
        Index("ix_moderation_actions__target", "target_type", "target_id", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    scope: Mapped[str] = mapped_column(Text, server_default=text("'platform'"))
    group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    target_type: Mapped[str] = mapped_column(Text)
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(Text)
    restriction_kind: Mapped[str | None] = mapped_column(Text)
    reason_code: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("content_reports.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
