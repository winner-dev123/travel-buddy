"""Durable jobs and the outbox relay (architecture section 7, ADR-0004).

* Producers call :func:`enqueue` (or ``platform.service.record_event``) inside their own
  transaction, so jobs/events exist if and only if the change committed.
* :class:`JobRunner.tick` does one bounded unit of work: recover jobs from crashed workers, relay
  unpublished outbox events into subscriber jobs, then claim and run due jobs. Workers call it in a
  loop (``python -m app.worker``); serverless deployments call it from cron and after responses.
* Claiming uses ``FOR UPDATE SKIP LOCKED``, so any number of runners can work concurrently.
* Handlers must be idempotent: delivery is at-least-once (a crash after the side effect but before
  ``complete`` runs the job again). Event-driven jobs carry the outbox ``event_id`` for that.
* All scheduling times (``run_at``, locks, retries) come from the DATABASE clock, the one clock
  every worker shares, so host clock skew cannot make jobs early, late or "stale".
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.ids import uuid7
from app.modules.platform.models import AsyncJob, JobStatus, OutboxEvent, PeriodicTask

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 10
_BACKOFF_BASE = timedelta(seconds=15)
_BACKOFF_CAP = timedelta(minutes=15)
_ERROR_MAX = 2000


def backoff(attempt: int) -> timedelta:
    """Delay before retry ``attempt`` (1-based): 15 s doubling to a 15 min cap.

    Ten attempts span about an hour, the contract's webhook delivery window.
    """
    if attempt < 1:
        raise ValueError("attempt is 1-based")
    delay: timedelta = _BACKOFF_BASE * (2 ** (attempt - 1))
    return min(delay, _BACKOFF_CAP)


class PermanentJobError(Exception):
    """The job can never succeed (e.g. the receiver rejected our signature): no retries."""


@dataclass(frozen=True, slots=True)
class Job:
    id: uuid.UUID
    queue: str
    kind: str
    payload: Mapping[str, Any]
    attempts: int
    max_attempts: int
    request_id: str | None


JobHandler = Callable[[Job], Awaitable[None]]


async def enqueue(
    session: AsyncSession,
    *,
    queue: str,
    kind: str,
    payload: Mapping[str, Any],
    dedupe_key: str | None = None,
    run_at: datetime | None = None,
    priority: int = 0,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    request_id: str | None = None,
) -> bool:
    """Add a job to the caller's transaction. Returns False when an active job with the same
    ``dedupe_key`` already exists (queued or running)."""
    values: dict[str, Any] = {
        "id": uuid7(),
        "queue": queue,
        "kind": kind,
        "payload": dict(payload),
        "priority": priority,
        "max_attempts": max_attempts,
        "dedupe_key": dedupe_key,
        "request_id": request_id,
    }
    if run_at is not None:
        values["run_at"] = run_at
    statement = (
        insert(AsyncJob)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=[AsyncJob.dedupe_key],
            index_where=text("dedupe_key IS NOT NULL AND status IN ('queued', 'running')"),
        )
        .returning(AsyncJob.id)
    )
    return (await session.execute(statement)).scalar_one_or_none() is not None


@dataclass(frozen=True, slots=True)
class Subscription:
    event_type: str
    queue: str
    kind: str
    # Filter on the event payload; events that do not match produce no job.
    when: Callable[[Mapping[str, Any]], bool] = field(default=lambda _payload: True)


class EventRouter:
    """Which jobs each outbox event type fans out to (wired in the composition root)."""

    def __init__(self) -> None:
        self._subscriptions: dict[str, list[Subscription]] = defaultdict(list)

    def subscribe(
        self,
        event_type: str,
        *,
        queue: str,
        kind: str,
        when: Callable[[Mapping[str, Any]], bool] | None = None,
    ) -> None:
        subscription = Subscription(event_type, queue, kind, when or (lambda _payload: True))
        self._subscriptions[event_type].append(subscription)

    def subscriptions_for(self, event_type: str) -> list[Subscription]:
        return list(self._subscriptions.get(event_type, ()))


async def relay_outbox(session: AsyncSession, router: EventRouter, *, limit: int = 100) -> int:
    """Turn unpublished outbox events into subscriber jobs and mark them published (one
    transaction, so a crash re-relays and dedupe keys absorb the duplicates)."""
    events = (
        await session.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.id)  # UUIDv7: creation order
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for event in events:
        for subscription in router.subscriptions_for(event.event_type):
            if not subscription.when(event.payload):
                continue
            await enqueue(
                session,
                queue=subscription.queue,
                kind=subscription.kind,
                payload={
                    "event_id": str(event.id),
                    "event_type": event.event_type,
                    "occurred_at": event.occurred_at.isoformat(),
                    "aggregate_id": str(event.aggregate_id),
                    "data": event.payload,
                },
                dedupe_key=f"{event.id}:{subscription.kind}",
                request_id=event.request_id,
            )
        event.published_at = func.now()
        event.attempts += 1
    await session.flush()
    return len(events)


@dataclass(slots=True)
class TickResult:
    relayed: int = 0
    succeeded: int = 0
    retried: int = 0
    dead: int = 0
    recovered: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "relayed": self.relayed,
            "succeeded": self.succeeded,
            "retried": self.retried,
            "dead": self.dead,
            "recovered": self.recovered,
        }


@dataclass(frozen=True, slots=True)
class Periodic:
    """A job enqueued every ``interval`` (first run on the first tick after deployment)."""

    name: str
    kind: str
    interval: timedelta
    queue: str = "default"


async def schedule_periodic(session: AsyncSession, tasks: Sequence[Periodic]) -> list[str]:
    """Enqueue every due periodic task once; returns the names enqueued."""
    if not tasks:
        return []
    await session.execute(
        insert(PeriodicTask)
        .values([{"name": t.name, "next_run_at": func.now()} for t in tasks])
        .on_conflict_do_nothing(index_elements=[PeriodicTask.name])
    )
    enqueued: list[str] = []
    for task in tasks:
        claimed = await session.execute(
            update(PeriodicTask)
            .where(PeriodicTask.name == task.name, PeriodicTask.next_run_at <= func.now())
            .values(next_run_at=func.now() + task.interval, last_run_at=func.now())
            .returning(PeriodicTask.name)
        )
        if claimed.first() is None:
            continue
        await enqueue(
            session,
            queue=task.queue,
            kind=task.kind,
            payload={"task": task.name},
            dedupe_key=f"periodic:{task.name}",
        )
        enqueued.append(task.name)
    return enqueued


class JobRunner:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        router: EventRouter,
        handlers: Mapping[str, JobHandler],
        queues: tuple[str, ...] = ("default",),
        worker_id: str | None = None,
        stale_after: timedelta = timedelta(minutes=5),
        periodic: Sequence[Periodic] = (),
    ) -> None:
        self._sessionmaker = sessionmaker
        self._periodic = tuple(periodic)
        self._router = router
        self._handlers = dict(handlers)
        self._queues = queues
        self._worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self._stale_after = stale_after

    async def tick(self, *, budget_seconds: float, max_jobs: int = 50) -> TickResult:
        deadline = time.monotonic() + budget_seconds
        result = TickResult()
        result.recovered = await self._recover_stale()
        if self._periodic:
            async with self._sessionmaker() as session, session.begin():
                scheduled = await schedule_periodic(session, self._periodic)
            if scheduled:
                logger.info("periodic tasks enqueued", extra={"tasks": scheduled})
        while time.monotonic() < deadline:
            async with self._sessionmaker() as session, session.begin():
                relayed = await relay_outbox(session, self._router)
            result.relayed += relayed
            if relayed < 100:
                break
        processed = 0
        while processed < max_jobs and time.monotonic() < deadline:
            job = await self._claim()
            if job is None:
                break
            processed += 1
            await self._run(job, result)
        return result

    async def _recover_stale(self) -> int:
        """Jobs left ``running`` by a crashed worker go back to the queue."""
        cutoff = func.now() - self._stale_after
        async with self._sessionmaker() as session, session.begin():
            recovered = await session.execute(
                update(AsyncJob)
                .where(and_(AsyncJob.status == JobStatus.RUNNING, AsyncJob.locked_at < cutoff))
                .values(status=JobStatus.QUEUED, locked_at=None, locked_by=None)
                .returning(AsyncJob.id)
            )
            count = len(recovered.all())
        if count:
            logger.warning("recovered stale jobs", extra={"count": count})
        return count

    async def _claim(self) -> Job | None:
        candidate = (
            select(AsyncJob.id)
            .where(
                AsyncJob.status == JobStatus.QUEUED,
                AsyncJob.queue.in_(self._queues),
                AsyncJob.run_at <= func.now(),
            )
            .order_by(AsyncJob.priority.desc(), AsyncJob.run_at)
            .limit(1)
            .with_for_update(skip_locked=True)
            .scalar_subquery()
        )
        async with self._sessionmaker() as session, session.begin():
            row = (
                await session.execute(
                    update(AsyncJob)
                    .where(AsyncJob.id == candidate)
                    .values(
                        status=JobStatus.RUNNING,
                        locked_at=func.now(),
                        locked_by=self._worker_id,
                        attempts=AsyncJob.attempts + 1,
                    )
                    .returning(
                        AsyncJob.id,
                        AsyncJob.queue,
                        AsyncJob.kind,
                        AsyncJob.payload,
                        AsyncJob.attempts,
                        AsyncJob.max_attempts,
                        AsyncJob.request_id,
                    )
                )
            ).first()
        if row is None:
            return None
        return Job(
            id=row.id,
            queue=row.queue,
            kind=row.kind,
            payload=row.payload,
            attempts=row.attempts,
            max_attempts=row.max_attempts,
            request_id=row.request_id,
        )

    async def _run(self, job: Job, result: TickResult) -> None:
        handler = self._handlers.get(job.kind)
        try:
            if handler is None:
                raise PermanentJobError(f"no handler registered for job kind {job.kind!r}")
            await handler(job)
        except PermanentJobError as exc:
            await self._finish(job, JobStatus.DEAD, error=str(exc))
            result.dead += 1
            logger.error("job failed permanently", extra={"kind": job.kind, "job_id": str(job.id)})
        except Exception as exc:  # retried with backoff; the error text is kept for operators
            if job.attempts >= job.max_attempts:
                await self._finish(job, JobStatus.DEAD, error=_describe(exc))
                result.dead += 1
                logger.error("job exhausted", extra={"kind": job.kind, "job_id": str(job.id)})
            else:
                await self._retry(job, error=_describe(exc))
                result.retried += 1
                logger.warning("job will retry", extra={"kind": job.kind, "job_id": str(job.id)})
        else:
            await self._finish(job, JobStatus.SUCCEEDED, error=None)
            result.succeeded += 1

    async def _finish(self, job: Job, status: JobStatus, *, error: str | None) -> None:
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                update(AsyncJob)
                .where(AsyncJob.id == job.id)
                .values(
                    status=status,
                    finished_at=func.now(),
                    locked_at=None,
                    locked_by=None,
                    last_error=error,
                )
            )

    async def _retry(self, job: Job, *, error: str) -> None:
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                update(AsyncJob)
                .where(AsyncJob.id == job.id)
                .values(
                    status=JobStatus.QUEUED,
                    run_at=func.now() + backoff(job.attempts),
                    locked_at=None,
                    locked_by=None,
                    last_error=error,
                )
            )


def _describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:_ERROR_MAX]
