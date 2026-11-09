"""PostgreSQL counter store for the rate limiter, for deployments without Redis (BL-1.15).

One ``INSERT … ON CONFLICT DO UPDATE … RETURNING`` per limit increments the current window and
reads the previous one. Each check runs in its own short transaction, independent of the request's.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.core.ratelimit.limiter import StoreUnavailableError, WindowHit
from app.modules.platform.models import RateLimitCounter

_PREVIOUS = aliased(RateLimitCounter)


class PostgresRateLimitStore:
    def __init__(
        self, sessionmaker: async_sessionmaker[AsyncSession], *, prune_every: int = 500
    ) -> None:
        self._sessionmaker = sessionmaker
        self._prune_every = prune_every
        self._calls = 0

    async def hit(self, hits: Sequence[WindowHit]) -> list[tuple[int, int]]:
        self._calls += 1
        try:
            async with self._sessionmaker() as session, session.begin():
                results = [await self._hit(session, hit) for hit in hits]
                if self._calls % self._prune_every == 0:
                    await session.execute(
                        delete(RateLimitCounter).where(RateLimitCounter.expires_at < func.now())
                    )
        except (SQLAlchemyError, OSError) as exc:
            raise StoreUnavailableError(type(exc).__name__) from exc
        return results

    @staticmethod
    async def _hit(session: AsyncSession, hit: WindowHit) -> tuple[int, int]:
        expires_at = datetime.fromtimestamp(hit.window_start, tz=UTC) + timedelta(
            seconds=2 * hit.window_seconds
        )
        previous = (
            select(_PREVIOUS.hits)
            .where(
                _PREVIOUS.key == hit.key,
                _PREVIOUS.window_start == hit.window_start - hit.window_seconds,
            )
            .scalar_subquery()
        )
        statement = (
            insert(RateLimitCounter)
            .values(key=hit.key, window_start=hit.window_start, hits=1, expires_at=expires_at)
            .on_conflict_do_update(
                index_elements=[RateLimitCounter.key, RateLimitCounter.window_start],
                set_={"hits": RateLimitCounter.hits + 1},
            )
            .returning(RateLimitCounter.hits, previous)
        )
        current, prior = (await session.execute(statement)).one()
        return int(current), int(prior or 0)
