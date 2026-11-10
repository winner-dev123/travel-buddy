"""Outbox and job queue health for the ops summary (ADM-006)."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform.models import AsyncJob, JobStatus, OutboxEvent


def _age(now: datetime, since: datetime | None) -> int | None:
    return max(0, int((now - since).total_seconds())) if since is not None else None


async def ops_stats(session: AsyncSession, now: datetime) -> dict[str, dict[str, int | None]]:
    unpublished, oldest_event = (
        await session.execute(
            select(func.count(), func.min(OutboxEvent.occurred_at)).where(
                OutboxEvent.published_at.is_(None)
            )
        )
    ).one()
    due, oldest_due = (
        await session.execute(
            select(func.count(), func.min(AsyncJob.run_at)).where(
                AsyncJob.status == JobStatus.QUEUED, AsyncJob.run_at <= now
            )
        )
    ).one()
    day_ago = now - timedelta(days=1)
    running, failed, dead = (
        await session.execute(
            select(
                func.count().filter(AsyncJob.status == JobStatus.RUNNING),
                func.count().filter(
                    AsyncJob.status == JobStatus.FAILED, AsyncJob.created_at >= day_ago
                ),
                func.count().filter(
                    AsyncJob.status == JobStatus.DEAD, AsyncJob.created_at >= day_ago
                ),
            )
        )
    ).one()
    return {
        "outbox": {
            "unpublished_events": int(unpublished),
            "oldest_unpublished_age_seconds": _age(now, oldest_event),
        },
        "jobs": {
            "queued_due": int(due),
            "running": int(running),
            "failed_last_24h": int(failed),
            "dead_last_24h": int(dead),
            "oldest_due_age_seconds": _age(now, oldest_due),
        },
    }
