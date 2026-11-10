"""Retention purges (BL-1.18, SAFE-009, docs/04 §14).

Each module owns a ``purge_expired(session) -> int`` that deletes at most one batch per table and
returns how many rows it removed. ``retention_handler`` runs it in fresh transactions until a round
removes nothing (or the round cap is hit; the next daily run continues), so locks stay short.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, delete, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.platform.jobs import Job, JobHandler
from app.modules.platform.models import (
    AsyncJob,
    IdempotencyKey,
    JobStatus,
    OutboxEvent,
    RateLimitCounter,
)

logger = logging.getLogger(__name__)

BATCH = 5000
MAX_ROUNDS = 20
DAILY = timedelta(days=1)

Purge = Callable[[AsyncSession], Awaitable[int]]


async def delete_batch(
    session: AsyncSession, model: type, condition: ColumnElement[bool], *, limit: int = BATCH
) -> int:
    """``DELETE … WHERE ctid IN (SELECT ctid … LIMIT n)``: works for any primary key shape."""
    ctid: ColumnElement[str] = literal_column("ctid")
    # correlate(None): the batch scans the table itself, not the DELETE target's current row.
    batch = select(ctid).select_from(model).where(condition).limit(limit).correlate(None)
    result = await session.execute(delete(model).where(ctid.in_(batch)))
    return int(getattr(result, "rowcount", 0) or 0)


def ago(**delta: float) -> ColumnElement[datetime]:
    """``now() - interval`` on the database clock."""
    return func.now() - timedelta(**delta)


async def purge_expired(session: AsyncSession) -> int:
    """Platform tables: idempotency keys past expiry, published outbox events after 7 days,
    succeeded jobs after 7 days and dead jobs after 30, expired rate-limit counters."""
    return sum(
        [
            await delete_batch(session, IdempotencyKey, IdempotencyKey.expires_at < func.now()),
            await delete_batch(session, OutboxEvent, OutboxEvent.published_at < ago(days=7)),
            await delete_batch(
                session,
                AsyncJob,
                (AsyncJob.status == JobStatus.SUCCEEDED) & (AsyncJob.finished_at < ago(days=7)),
            ),
            await delete_batch(
                session,
                AsyncJob,
                (AsyncJob.status == JobStatus.DEAD) & (AsyncJob.finished_at < ago(days=30)),
            ),
            await delete_batch(session, RateLimitCounter, RateLimitCounter.expires_at < func.now()),
        ]
    )


def retention_handler(
    sessionmaker: async_sessionmaker[AsyncSession], purge: Purge, *, name: str
) -> JobHandler:
    async def handle(job: Job) -> None:
        total = 0
        for _ in range(MAX_ROUNDS):
            async with sessionmaker() as session, session.begin():
                removed = await purge(session)
            total += removed
            if removed == 0:
                break
        # "module" is a LogRecord attribute: passing it in `extra` raises once INFO is enabled.
        logger.info("retention purge", extra={"purge_module": name, "removed": total})

    return handle
