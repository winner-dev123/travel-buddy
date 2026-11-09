"""UUIDv7 generation (RFC 9562), monotonic within a process (ADR-0007).

Layout: 48-bit Unix epoch milliseconds | ver(4)=7 | rand_a(12) | var(2)=0b10 | rand_b(62).
``rand_a`` is used as a per-millisecond counter seeded randomly, so IDs generated in the same
millisecond by this process sort in creation order.
"""

from __future__ import annotations

import secrets
import threading
import time
import uuid

_MAX_TIMESTAMP_MS = (1 << 48) - 1
_COUNTER_MAX = 0xFFF

_lock = threading.Lock()
_last_ms = 0
_counter = 0


def uuid7() -> uuid.UUID:
    """Return a new time-ordered UUIDv7."""
    global _last_ms, _counter
    with _lock:
        now_ms = time.time_ns() // 1_000_000
        if now_ms > _last_ms:
            _last_ms = now_ms
            # Seed in the lower half so the counter has room to increment within this ms.
            _counter = secrets.randbits(11)
        else:
            _counter += 1
            if _counter > _COUNTER_MAX:
                # Counter exhausted for this millisecond: advance the logical clock.
                _last_ms += 1
                _counter = 0
        timestamp_ms = _last_ms & _MAX_TIMESTAMP_MS
        rand_a = _counter
    rand_b = secrets.randbits(62)
    value = (timestamp_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)


def uuid7_timestamp_ms(value: uuid.UUID) -> int:
    """Extract the Unix epoch milliseconds embedded in a UUIDv7."""
    if value.version != 7:
        raise ValueError("not a UUIDv7")
    return value.int >> 80
