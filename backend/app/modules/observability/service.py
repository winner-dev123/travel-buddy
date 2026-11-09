"""Public interface of the observability module: the append-only audit log (SAFE-007, ADM-009).

Rows are written inside the transaction of the action they describe, so an action and its audit
entry commit together. The table rejects UPDATE and DELETE (database trigger).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

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
