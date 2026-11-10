"""Public interface of the platform module: transactional outbox and durable jobs (ADR-0004).

Producers call :func:`record_event` inside the transaction that changes state, so an event exists
if and only if the change committed. The relay (``jobs.relay_outbox``) turns events into jobs.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from contextvars import ContextVar
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.core.request_context import current_request_id
from app.modules.platform import idempotency
from app.modules.platform.export import export_rows, jsonable
from app.modules.platform.jobs import (
    EventRouter,
    Job,
    JobHandler,
    JobRunner,
    Periodic,
    PermanentJobError,
    TickResult,
    backoff,
    enqueue,
)
from app.modules.platform.models import OutboxEvent
from app.modules.platform.ops import ops_stats
from app.modules.platform.ratelimit import PostgresRateLimitStore
from app.modules.platform.retention import (
    DAILY,
    ago,
    delete_batch,
    retention_handler,
)
from app.modules.platform.retention import purge_expired as purge_platform

__all__ = [
    "DAILY",
    "EventRouter",
    "Job",
    "JobHandler",
    "JobRunner",
    "OutboxSignal",
    "Periodic",
    "PermanentJobError",
    "PostgresRateLimitStore",
    "TickResult",
    "ago",
    "backoff",
    "delete_batch",
    "enqueue",
    "export_rows",
    "idempotency",
    "jsonable",
    "ops_stats",
    "purge_platform",
    "record_event",
    "retention_handler",
    "track_outbox_events",
]


class OutboxSignal:
    """Set when the current request recorded at least one outbox event."""

    __slots__ = ("recorded",)

    def __init__(self) -> None:
        self.recorded = False


_outbox_signal: ContextVar[OutboxSignal | None] = ContextVar("outbox_signal", default=None)


def track_outbox_events() -> OutboxSignal:
    """Start tracking for the current request (used by the after-response tick middleware)."""
    signal = OutboxSignal()
    _outbox_signal.set(signal)
    return signal


def record_event(
    session: AsyncSession,
    *,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    event_type: str,
    payload: Mapping[str, Any],
) -> uuid.UUID:
    """Add an outbox row to the caller's transaction; returns the event ID (consumers' dedupe key).

    Payloads carry IDs, changed field names and already-public identifiers (such as handles),
    never private personal data.
    """
    event = OutboxEvent(
        id=uuid7(),  # assigned now so the caller gets it before flush
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=dict(payload),
        request_id=current_request_id(),
    )
    session.add(event)
    signal = _outbox_signal.get()
    if signal is not None:
        signal.recorded = True
    return event.id
