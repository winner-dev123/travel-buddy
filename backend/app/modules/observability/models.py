"""Append-only audit log (docs/04 section 12, requirement SAFE-007).

Append-only is enforced in the database by a trigger (see migration 0001), so it holds even if
application code or a privileged role attempts UPDATE/DELETE. Partitioning by month is deferred
to Phase 6 (docs/04 section 15).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Index, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_check
from app.core.ids import uuid7


class ActorType(StrEnum):
    USER = "user"
    ADMIN = "admin"
    SYSTEM = "system"
    SERVICE = "service"


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        enum_check("actor_type", ActorType, "actor_type_enum"),
        Index(
            "ix_audit_logs__resource",
            "resource_type",
            "resource_id",
            text("occurred_at DESC"),
        ),
        Index("ix_audit_logs__actor", "actor_id", text("occurred_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    actor_type: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    resource_type: Mapped[str] = mapped_column(Text)
    resource_id: Mapped[str] = mapped_column(Text)
    scope_group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    request_id: Mapped[str | None] = mapped_column(Text)
    # Python attribute "details" (``metadata`` is reserved by SQLAlchemy); column "metadata".
    details: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )
    ip: Mapped[str | None] = mapped_column(INET)
