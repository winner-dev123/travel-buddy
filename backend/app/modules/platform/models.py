"""Platform tables (docs/04 section 12). Private to the platform module."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
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


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DEAD = "dead"


class IdempotencyStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index(
            "ix_outbox_events__unpublished",
            "id",
            postgresql_where=text("published_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    aggregate_type: Mapped[str] = mapped_column(Text)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    event_type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class AsyncJob(Base):
    __tablename__ = "asynchronous_jobs"
    __table_args__ = (
        enum_check("status", JobStatus, "status_enum"),
        Index(
            "ix_asynchronous_jobs__claimable",
            "queue",
            text("priority DESC"),
            "run_at",
            postgresql_where=text("status = 'queued'"),
        ),
        Index(
            "uq_asynchronous_jobs__active_dedupe_key",
            "dedupe_key",
            unique=True,
            postgresql_where=text("dedupe_key IS NOT NULL AND status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    queue: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'queued'"))
    priority: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    max_attempts: Mapped[int] = mapped_column(Integer, server_default=text("10"))
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "key"),
        enum_check("status", IdempotencyStatus, "status_enum"),
        Index("ix_idempotency_keys__expires_at", "expires_at"),
    )

    # FK to users is added by the Phase 1 identity migration (the users table does not exist yet).
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    key: Mapped[uuid.UUID] = mapped_column(Uuid)
    route: Mapped[str] = mapped_column(Text)
    request_hash: Mapped[bytes] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(Text, server_default=text("'in_progress'"))
    response_status: Mapped[int | None] = mapped_column(SmallInteger)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
