"""Public interface of the observability module: the append-only audit log (SAFE-007, ADM-009).

Rows are written inside the transaction of the action they describe, so an action and its audit
entry commit together. The table rejects UPDATE and DELETE (database trigger).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.request_context import current_request_id
from app.modules.observability.models import AuditLog


def audit(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    actor_type: str,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | str,
    justification: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    """Record who did what to which resource, and why (``justification`` from the staff header)."""
    details: dict[str, Any] = dict(metadata or {})
    if justification is not None:
        details["justification"] = justification
    session.add(
        AuditLog(
            actor_id=actor_id,
            actor_type=actor_type,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id),
            request_id=current_request_id(),
            details=details,
        )
    )


async def query(
    session: AsyncSession,
    *,
    resource_type: str | None,
    resource_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    start: datetime | None,
    end: datetime | None,
    after: tuple[datetime, uuid.UUID] | None,
    limit: int,
) -> Sequence[AuditLog]:
    """Audit entries, newest first (ADM-002); ``after`` is the last ``(occurred_at, id)`` seen."""
    conditions: list[Any] = []
    if resource_type is not None:
        conditions.append(AuditLog.resource_type == resource_type)
    if resource_id is not None:
        conditions.append(AuditLog.resource_id == str(resource_id))
    if actor_id is not None:
        conditions.append(AuditLog.actor_id == actor_id)
    if start is not None:
        conditions.append(AuditLog.occurred_at >= start)
    if end is not None:
        conditions.append(AuditLog.occurred_at < end)
    if after is not None:
        conditions.append(
            tuple_(AuditLog.occurred_at, AuditLog.id) < tuple_(literal(after[0]), literal(after[1]))
        )
    return (
        await session.scalars(
            select(AuditLog)
            .where(*conditions)
            .order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
            .limit(limit)
        )
    ).all()
