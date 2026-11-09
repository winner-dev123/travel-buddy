"""Counter stores for the rate limiter: memory (development) and Redis (production).

The PostgreSQL store lives in the platform module (it owns the table); all stores implement
``RateLimitStore`` from ``app.core.ratelimit.limiter``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.ratelimit.limiter import StoreUnavailableError, WindowHit


class MemoryRateLimitStore:
    """Single-process counters. Development and tests only (not shared between instances)."""

    def __init__(self) -> None:
        self._counts: dict[tuple[str, int], int] = {}
        self._lock = asyncio.Lock()

    async def hit(self, hits: Sequence[WindowHit]) -> list[tuple[int, int]]:
        async with self._lock:
            results: list[tuple[int, int]] = []
            for hit in hits:
                current_key = (hit.key, hit.window_start)
                self._counts[current_key] = self._counts.get(current_key, 0) + 1
                previous = self._counts.get((hit.key, hit.window_start - hit.window_seconds), 0)
                results.append((self._counts[current_key], previous))
            if len(self._counts) > 50_000:
                self._prune(hits)
            return results

    def _prune(self, hits: Sequence[WindowHit]) -> None:
        horizon = min(h.window_start - 2 * h.window_seconds for h in hits)
        self._counts = {k: v for k, v in self._counts.items() if k[1] >= horizon}


class RedisRateLimitStore:
    """``INCR`` + ``EXPIRE`` on the current window and ``GET`` of the previous, in one pipeline."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def hit(self, hits: Sequence[WindowHit]) -> list[tuple[int, int]]:
        try:
            async with self._redis.pipeline(transaction=False) as pipe:
                for hit in hits:
                    current = f"{hit.key}:{hit.window_start}"
                    pipe.incr(current)
                    pipe.expire(current, 2 * hit.window_seconds + 5)
                    pipe.get(f"{hit.key}:{hit.window_start - hit.window_seconds}")
                replies = await pipe.execute()
        except (RedisError, OSError) as exc:
            raise StoreUnavailableError(str(exc)) from exc
        return [(int(replies[i * 3]), int(replies[i * 3 + 2] or 0)) for i in range(len(hits))]
