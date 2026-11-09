"""Stored-response idempotency for creating requests (BL-1.15, contract ``Idempotency-Key``).

Use inside the SAME transaction as the write it protects::

    replay = await claim(session, user_id=..., key=..., route="POST /v1/posts", payload=body)
    if replay is not None:
        return replay          # same key + same body: the original response
    ... perform the write ...
    await complete(session, user_id=..., key=..., status=201, body=response_json)

Because the claim row is inserted in the writer's transaction, a concurrent duplicate blocks on the
primary key until the first request commits and then replays its stored response. A failed or
rolled-back request leaves no row, so the client can simply retry.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.modules.platform.models import IdempotencyKey, IdempotencyStatus

RETENTION = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class Replay:
    status: int
    body: Any


def request_hash(route: str, payload: Mapping[str, Any]) -> bytes:
    canonical = json.dumps({"route": route, "body": payload}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).digest()


async def claim(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    key: uuid.UUID,
    route: str,
    payload: Mapping[str, Any],
) -> Replay | None:
    """``None`` = proceed with the write; a :class:`Replay` = return the stored response."""
    digest = request_hash(route, payload)
    for _ in range(2):  # second pass after discarding an expired key
        inserted = await session.execute(
            insert(IdempotencyKey)
            .values(
                user_id=user_id,
                key=key,
                route=route,
                request_hash=digest,
                status=IdempotencyStatus.IN_PROGRESS,
                expires_at=func.now() + RETENTION,
            )
            .on_conflict_do_nothing(index_elements=[IdempotencyKey.user_id, IdempotencyKey.key])
            .returning(IdempotencyKey.key)
        )
        if inserted.first() is not None:
            return None
        existing = await session.get(IdempotencyKey, (user_id, key), populate_existing=True)
        if existing is None:
            continue  # deleted concurrently; claim again
        db_now = await session.scalar(select(func.now()))
        if db_now is not None and existing.expires_at <= db_now:
            await session.execute(
                delete(IdempotencyKey).where(
                    IdempotencyKey.user_id == user_id, IdempotencyKey.key == key
                )
            )
            continue
        if existing.route != route or existing.request_hash != digest:
            raise AppError(
                ErrorCode.IDEMPOTENCY_KEY_REUSED,
                "This Idempotency-Key was already used for a different request.",
            )
        if existing.status != IdempotencyStatus.COMPLETED or existing.response_status is None:
            raise AppError(
                ErrorCode.IDEMPOTENCY_KEY_IN_PROGRESS,
                "A request with this Idempotency-Key is still being processed.",
            )
        return Replay(status=existing.response_status, body=existing.response_body)
    raise AppError(  # pragma: no cover - two consecutive races on the same key
        ErrorCode.IDEMPOTENCY_KEY_IN_PROGRESS, "Please retry the request."
    )


async def complete(
    session: AsyncSession, *, user_id: uuid.UUID, key: uuid.UUID, status: int, body: Any
) -> None:
    await session.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.user_id == user_id, IdempotencyKey.key == key)
        .values(status=IdempotencyStatus.COMPLETED, response_status=status, response_body=body)
    )
