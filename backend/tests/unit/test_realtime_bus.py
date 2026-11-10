"""Realtime bus and frame helpers (BL-3.04; docs/06 §3, §10)."""

from __future__ import annotations

import uuid

import pytest

from app.realtime.bus import BUFFER_FRAMES, MemoryBus
from app.realtime.frames import AuthData, Envelope, error_code, frame
from tests.contract_schemas import assert_realtime_frame


async def test_memory_bus_delivers_per_user_copies_and_stops_after_close() -> None:
    bus = MemoryBus()
    ana, bo = uuid.uuid4(), uuid.uuid4()
    first, second, other = (
        await bus.subscribe(ana),
        await bus.subscribe(ana),
        await bus.subscribe(bo),
    )
    event = {"type": "typing", "data": {"n": 1}}
    await bus.publish([ana, ana], event)
    got = await first.get()
    assert got == event
    got["data"]["n"] = 2  # each connection has its own copy
    assert await second.get() == event
    await first.close()
    await bus.publish([ana, bo], {"type": "pong", "data": {}})
    assert (await second.get())["type"] == "pong"
    assert (await other.get())["type"] == "pong"


async def test_memory_bus_replaces_an_overflowing_buffer_with_a_resync() -> None:
    bus = MemoryBus()
    user = uuid.uuid4()
    subscription = await bus.subscribe(user)
    for index in range(BUFFER_FRAMES + 1):
        await bus.publish([user], {"type": "typing", "data": {"i": index}})
    resync = await subscription.get()
    assert resync["type"] == "sync.required"
    assert resync["data"]["reason"] == "backpressure"
    assert resync["data"]["full_resync"] is True


def test_server_frames_match_the_envelope() -> None:
    reply = uuid.uuid4()
    pong = frame("pong", {"server_time": "2026-11-09T12:00:00Z"}, reply_to=reply)
    assert pong["reply_to"] == str(reply)
    assert_realtime_frame(pong)


def test_client_envelope_rejects_reply_to_and_auth_needs_one_credential() -> None:
    raw = {"v": 1, "type": "ping", "id": str(uuid.uuid4()), "ts": "2026-11-09T12:00:00Z"}
    assert Envelope.model_validate(raw).data == {}
    with pytest.raises(ValueError):
        Envelope.model_validate({**raw, "reply_to": str(uuid.uuid4())})
    with pytest.raises(ValueError):
        AuthData.model_validate({})
    with pytest.raises(ValueError):
        AuthData.model_validate({"access_token": "x" * 30, "ticket": "a" * 43})


@pytest.mark.parametrize(
    ("code", "status", "expected"),
    [
        ("connection_required", 403, "connection_required"),
        ("blocked_relationship", 403, "forbidden"),
        ("account_restricted", 403, "forbidden"),
        ("validation_failed", 422, "validation_failed"),
        ("already_connected", 409, "conflict"),
        ("something_new", 500, "internal_error"),
    ],
)
def test_error_codes_map_to_the_realtime_subset(code: str, status: int, expected: str) -> None:
    assert error_code(code, status) == expected
