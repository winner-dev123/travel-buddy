"""Connection tables (docs/04 §6). Private to the connections module."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_check
from app.core.ids import uuid7
from app.modules.connections.domain import RequestStatus


class ConnectionContext:
    VALUES = ("discovery", "group", "profile", "post")


class ConnectionRequest(Base):
    __tablename__ = "connection_requests"
    __table_args__ = (
        enum_check("status", RequestStatus, "status_enum"),
        enum_check("context", ConnectionContext.VALUES, "context_enum"),
        CheckConstraint("requester_id <> recipient_id", name="not_self"),
        CheckConstraint("char_length(note) <= 140", name="note_length"),
        Index(
            "uq_connection_requests__pending_pair",
            "requester_id",
            "recipient_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_connection_requests__inbox", "recipient_id", "status", text("created_at DESC")),
        Index("ix_connection_requests__outbox", "requester_id", "status", text("created_at DESC")),
        Index(
            "ix_connection_requests__pair_responded",
            "requester_id",
            "recipient_id",
            text("responded_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    requester_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    context: Mapped[str] = mapped_column(Text)
    context_ref_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UserConnection(Base):
    """One row per connected pair, canonically ordered (``user_low_id < user_high_id``)."""

    __tablename__ = "user_connections"
    __table_args__ = (
        PrimaryKeyConstraint("user_low_id", "user_high_id"),
        CheckConstraint("user_low_id < user_high_id", name="ordered"),
        Index("ix_user_connections__user_high_id", "user_high_id"),
    )

    user_low_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    user_high_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    source_request_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("connection_requests.id", ondelete="SET NULL")
    )
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
