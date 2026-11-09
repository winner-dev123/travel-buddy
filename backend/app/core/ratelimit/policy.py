"""Rate-limit classes, initial limits and failure modes (docs/05 §5, SAFE-005, NFR-006).

Every operation in the contract declares an ``x-rate-limit-class``. A class has one or more
limits; a *bucket* is a named variant used by specific operations (reports: 20/day instead of the
``sensitive`` default of 10/h). Buckets inherit the failure mode of their class. Values are the
initial ones from docs/05 and can be overridden per environment with ``RATE_LIMITS``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class RateClass(StrEnum):
    NONE = "none"
    READ = "read"
    WRITE = "write"
    SEARCH = "search"
    GUEST = "guest"
    AUTH = "auth"
    SENSITIVE = "sensitive"
    CONTACT = "contact"
    DISCOVERY = "discovery"
    MESSAGE = "message"
    SUBMISSION = "submission"
    MEDIA_UPLOAD = "media_upload"
    AI = "ai"
    BILLING = "billing"
    REALTIME_TICKET = "realtime_ticket"
    WEBHOOK = "webhook"
    ADMIN = "admin"


class Scope(StrEnum):
    """Who a limit is counted against."""

    USER = "user"  # the signed-in user; anonymous callers fall back to their IP
    IP = "ip"  # always the client IP (guests, sign-in)
    KEY = "key"  # an explicit key supplied by the caller (IdP subject, session, provider)


@dataclass(frozen=True, slots=True)
class Limit:
    limit: int
    window_seconds: int

    def __post_init__(self) -> None:
        if self.limit < 1 or not 1 <= self.window_seconds <= 7 * 86400:
            raise ValueError(f"invalid limit {self.limit}/{self.window_seconds}s")

    def __str__(self) -> str:
        return f"{self.limit}/{self.window_seconds}"


@dataclass(frozen=True, slots=True)
class Bucket:
    name: str
    rate_class: RateClass
    scope: Scope
    limits: tuple[Limit, ...]

    @property
    def fails_closed(self) -> bool:
        return self.rate_class in FAILS_CLOSED


MINUTE, HOUR, DAY = 60, 3600, 86400

# Classes that reject requests when the counter store is unavailable (docs/05 §5).
FAILS_CLOSED: frozenset[RateClass] = frozenset(
    {
        RateClass.GUEST,
        RateClass.AUTH,
        RateClass.SENSITIVE,
        RateClass.CONTACT,
        RateClass.DISCOVERY,
        RateClass.MEDIA_UPLOAD,
        RateClass.AI,
        RateClass.BILLING,
        RateClass.REALTIME_TICKET,
    }
)

_DEFAULTS: tuple[tuple[str, RateClass, Scope, tuple[Limit, ...]], ...] = (
    ("read", RateClass.READ, Scope.USER, (Limit(600, MINUTE),)),
    ("write", RateClass.WRITE, Scope.USER, (Limit(120, MINUTE),)),
    ("search", RateClass.SEARCH, Scope.USER, (Limit(60, MINUTE),)),
    ("guest", RateClass.GUEST, Scope.IP, (Limit(60, MINUTE),)),
    ("auth", RateClass.AUTH, Scope.IP, (Limit(10, MINUTE),)),
    ("auth_subject", RateClass.AUTH, Scope.KEY, (Limit(20, HOUR),)),
    ("auth_refresh", RateClass.AUTH, Scope.KEY, (Limit(60, HOUR),)),
    ("sensitive", RateClass.SENSITIVE, Scope.USER, (Limit(10, HOUR),)),
    ("reports", RateClass.SENSITIVE, Scope.USER, (Limit(20, DAY),)),
    ("data_export", RateClass.SENSITIVE, Scope.USER, (Limit(2, DAY),)),
    ("invitation", RateClass.SENSITIVE, Scope.USER, (Limit(30, HOUR),)),
    ("contact", RateClass.CONTACT, Scope.USER, (Limit(20, DAY), Limit(5, MINUTE))),
    ("group_invitations", RateClass.CONTACT, Scope.USER, (Limit(50, DAY),)),
    ("join_requests", RateClass.CONTACT, Scope.USER, (Limit(20, DAY),)),
    ("discovery", RateClass.DISCOVERY, Scope.USER, (Limit(60, MINUTE), Limit(500, DAY))),
    ("message", RateClass.MESSAGE, Scope.USER, (Limit(30, MINUTE), Limit(10, 10))),
    ("conversation", RateClass.MESSAGE, Scope.KEY, (Limit(20, MINUTE),)),
    ("submission", RateClass.SUBMISSION, Scope.USER, (Limit(10, MINUTE),)),
    ("media_upload", RateClass.MEDIA_UPLOAD, Scope.USER, (Limit(30, HOUR),)),
    ("ai", RateClass.AI, Scope.USER, (Limit(10, HOUR),)),
    ("billing", RateClass.BILLING, Scope.USER, (Limit(20, HOUR),)),
    ("realtime_ticket", RateClass.REALTIME_TICKET, Scope.KEY, (Limit(30, MINUTE),)),
    ("webhook", RateClass.WEBHOOK, Scope.KEY, (Limit(1000, MINUTE),)),
    ("admin", RateClass.ADMIN, Scope.USER, (Limit(300, MINUTE),)),
)

_LIMIT_SPEC = re.compile(r"^\s*(\d+)\s*/\s*(\d+)\s*$")


def parse_limits(spec: str) -> tuple[Limit, ...]:
    """``"20/86400, 5/60"`` → limits (count per window in seconds)."""
    limits: list[Limit] = []
    for part in spec.split(","):
        match = _LIMIT_SPEC.match(part)
        if match is None:
            raise ValueError(f"invalid rate limit {part!r}; expected '<count>/<seconds>'")
        limits.append(Limit(int(match[1]), int(match[2])))
    return tuple(limits)


@dataclass(frozen=True, slots=True)
class RatePolicy:
    buckets: Mapping[str, Bucket]

    @classmethod
    def build(cls, overrides: Mapping[str, str] | None = None) -> RatePolicy:
        buckets = {
            name: Bucket(name, rate_class, scope, limits)
            for name, rate_class, scope, limits in _DEFAULTS
        }
        for name, spec in (overrides or {}).items():
            if name not in buckets:
                raise ValueError(f"unknown rate limit bucket {name!r}")
            current = buckets[name]
            buckets[name] = Bucket(name, current.rate_class, current.scope, parse_limits(spec))
        return cls(buckets)

    def bucket(self, name: str) -> Bucket:
        return self.buckets[name]


def bucket_names() -> frozenset[str]:
    return frozenset(name for name, *_ in _DEFAULTS)
