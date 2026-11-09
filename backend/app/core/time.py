"""Injectable clock so time-dependent domain logic is deterministic in tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(tz=UTC)


class FixedClock:
    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FixedClock requires an aware datetime")
        self._at = at

    def now(self) -> datetime:
        return self._at

    def set(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FixedClock requires an aware datetime")
        self._at = at


def require_aware(value: datetime, name: str = "datetime") -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value
