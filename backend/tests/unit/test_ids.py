from __future__ import annotations

import time
import uuid

import pytest

from app.core.ids import uuid7, uuid7_timestamp_ms


def test_uuid7_version_and_variant() -> None:
    value = uuid7()
    assert value.version == 7
    assert value.variant == uuid.RFC_4122


def test_uuid7_is_monotonic_and_unique_within_process() -> None:
    ids = [uuid7() for _ in range(20_000)]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)


def test_uuid7_embeds_current_timestamp() -> None:
    before = time.time_ns() // 1_000_000
    value = uuid7()
    after = time.time_ns() // 1_000_000
    # The logical clock may run slightly ahead when the per-ms counter overflows.
    assert before <= uuid7_timestamp_ms(value) <= after + 50


def test_timestamp_extraction_rejects_other_versions() -> None:
    with pytest.raises(ValueError, match="UUIDv7"):
        uuid7_timestamp_ms(uuid.uuid4())
