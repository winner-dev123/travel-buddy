"""Public interface of the platform module: the transactional outbox (architecture section 7.1).

Producers call :func:`record_event` inside the transaction that changes state, so an event exists
if and only if the change committed. The relay that publishes events (BL-1.09) is separate.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.core.request_context import current_request_id
from app.modules.platform.models import OutboxEvent


def record_event(
    session: AsyncSession,
    *,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    event_type: str,
    payload: Mapping[str, Any],
) -> uuid.UUID:
    """Add an outbox row to the caller's transaction; returns the event ID (consumers' dedupe key).

    Payloads carry IDs and changed field names, never personal data that consumers can re-read.
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
    return event.id
