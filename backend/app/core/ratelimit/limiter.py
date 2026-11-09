"""Sliding-window rate limiter (approximated with two fixed windows, as in docs/02 §15).

For each limit the store returns the hit count of the current fixed window (this request
included) and of the previous one. The estimate is ``previous * (1 - elapsed / window) +
current``; the request is allowed while the estimate stays within the limit. Rejected requests
are counted too, so a client that keeps hammering stays limited until it backs off.

The store is pluggable: Redis in production, PostgreSQL where no Redis exists (serverless
staging), memory for development. When the store fails, classes that fail *open* let the request
through and classes that fail *closed* reject it (docs/05 §5).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.core.errors import AppError, ErrorCode
from app.core.ratelimit.policy import Bucket, Limit, RatePolicy
from app.core.time import Clock

logger = logging.getLogger(__name__)

UNAVAILABLE_RETRY_SECONDS = 5


class StoreUnavailableError(Exception):
    """The counter store could not be reached."""


@dataclass(frozen=True, slots=True)
class WindowHit:
    key: str
    window_start: int  # epoch seconds, a multiple of the window length
    window_seconds: int


class RateLimitStore(Protocol):
    async def hit(self, hits: Sequence[WindowHit]) -> list[tuple[int, int]]:
        """Increment each current window; return ``(current, previous)`` counts per hit."""
        ...


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int
    retry_after_seconds: int = 0

    def headers(self) -> dict[str, str]:
        headers = {
            "RateLimit-Limit": str(self.limit),
            "RateLimit-Remaining": str(self.remaining),
            "RateLimit-Reset": str(self.reset_seconds),
        }
        if not self.allowed:
            headers["Retry-After"] = str(self.retry_after_seconds)
        return headers


def evaluate(limit: Limit, *, current: int, previous: int, elapsed: float) -> Decision:
    """Pure sliding-window decision for one limit (``current`` includes this request)."""
    window = limit.window_seconds
    elapsed = min(max(elapsed, 0.0), float(window))
    estimate = previous * (1 - elapsed / window) + current
    allowed = estimate <= limit.limit
    remaining = max(0, math.floor(limit.limit - estimate))
    reset = max(1, math.ceil(window - elapsed))
    retry = 0
    if not allowed:
        if current >= limit.limit:
            # The current window alone is full: wait for it to end, then for its weight to decay
            # far enough for one more request.
            decay = window * (1 - (limit.limit - 1) / current)
            retry = math.ceil(window - elapsed + max(0.0, decay))
        else:
            needed = window * (1 - (limit.limit - 1 - current) / previous) - elapsed
            retry = math.ceil(max(1.0, needed))
        retry = max(1, retry)
    return Decision(allowed, limit.limit, remaining, reset, retry)


def most_restrictive(decisions: Sequence[Decision]) -> Decision:
    rejected = [d for d in decisions if not d.allowed]
    if rejected:
        return max(rejected, key=lambda d: d.retry_after_seconds)
    return min(decisions, key=lambda d: (d.remaining, -d.reset_seconds))


class RateLimiter:
    def __init__(self, store: RateLimitStore, policy: RatePolicy, clock: Clock) -> None:
        self._store = store
        self._policy = policy
        self._clock = clock

    @property
    def policy(self) -> RatePolicy:
        return self._policy

    async def check(self, bucket: Bucket, subject: str) -> Decision:
        """Count one request against every limit of ``bucket`` for ``subject``."""
        now = self._clock.now().timestamp()
        hits = [
            WindowHit(
                key=f"rl:{bucket.name}:{limit.limit}/{limit.window_seconds}:{subject}",
                window_start=int(now // limit.window_seconds) * limit.window_seconds,
                window_seconds=limit.window_seconds,
            )
            for limit in bucket.limits
        ]
        try:
            counts = await self._store.hit(hits)
        except StoreUnavailableError:
            if bucket.fails_closed:
                logger.warning("rate_limit_store_unavailable_closed", extra={"bucket": bucket.name})
                raise AppError(
                    ErrorCode.SERVICE_UNAVAILABLE,
                    "Temporarily unavailable. Try again shortly.",
                    headers={"Retry-After": str(UNAVAILABLE_RETRY_SECONDS)},
                ) from None
            logger.warning("rate_limit_store_unavailable_open", extra={"bucket": bucket.name})
            return Decision(True, bucket.limits[0].limit, bucket.limits[0].limit, 0)
        decisions = [
            evaluate(limit, current=current, previous=previous, elapsed=now - hit.window_start)
            for limit, hit, (current, previous) in zip(bucket.limits, hits, counts, strict=True)
        ]
        return most_restrictive(decisions)

    async def enforce(self, bucket_name: str, subject: str) -> Decision:
        """Check and raise ``429 rate_limited`` (with ``Retry-After``) when over the limit."""
        decision = await self.check(self._policy.bucket(bucket_name), subject)
        if not decision.allowed:
            raise AppError(
                ErrorCode.RATE_LIMITED,
                "Too many requests. Slow down and try again later.",
                headers=decision.headers(),
            )
        return decision
