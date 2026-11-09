from __future__ import annotations

import pytest

from app.core.errors import AppError, ErrorCode
from app.core.pagination import (
    DEFAULT_LIMIT,
    MAX_CURSOR_LENGTH,
    MAX_LIMIT,
    CursorCodec,
    Page,
    PageInfo,
    clamp_limit,
)

KEY = b"k" * 32


class _Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _codec(clock: _Clock | None = None, ttl: int = 600) -> CursorCodec:
    return CursorCodec(KEY, ttl_seconds=ttl, clock=clock or _Clock(1_000_000.0))


def _assert_invalid(codec: CursorCodec, token: str, scope: str = "feed") -> None:
    with pytest.raises(AppError) as excinfo:
        codec.decode(token, scope=scope)
    assert excinfo.value.code is ErrorCode.INVALID_CURSOR
    assert excinfo.value.status == 400


@pytest.mark.req("FEED-004")
def test_round_trip() -> None:
    codec = _codec()
    token = codec.encode({"session": "abc", "offset": 40}, scope="feed")
    assert codec.decode(token, scope="feed") == {"session": "abc", "offset": 40}


def test_tampered_payload_rejected() -> None:
    codec = _codec()
    token = codec.encode({"offset": 40}, scope="feed")
    body, sig = token.split(".")
    forged_body = codec.encode({"offset": 4000}, scope="feed").split(".")[0]
    _assert_invalid(codec, f"{forged_body}.{sig}")
    _assert_invalid(codec, f"{body}.{'A' * len(sig)}")


def test_cursor_from_other_key_rejected() -> None:
    other = CursorCodec(b"x" * 32, ttl_seconds=600, clock=_Clock(1_000_000.0))
    _assert_invalid(_codec(), other.encode({"offset": 1}, scope="feed"))


def test_scope_binding() -> None:
    codec = _codec()
    token = codec.encode({"offset": 1}, scope="feed:for_you:dest=rio")
    _assert_invalid(codec, token, scope="feed:following")


def test_expiry_and_future_timestamps() -> None:
    clock = _Clock(1_000_000.0)
    codec = _codec(clock, ttl=600)
    token = codec.encode({"offset": 1}, scope="feed")
    clock.now += 601
    _assert_invalid(codec, token)

    future_codec = _codec(_Clock(2_000_000.0))
    future_token = future_codec.encode({"offset": 1}, scope="feed")
    _assert_invalid(codec, future_token)


@pytest.mark.parametrize("token", ["", "abc", "a.b.c", "!!!.???", "e30.AAAA"])
def test_malformed_tokens_rejected(token: str) -> None:
    _assert_invalid(_codec(), token)


def test_oversized_token_rejected() -> None:
    _assert_invalid(_codec(), "a" * (MAX_CURSOR_LENGTH + 1))


def test_short_key_rejected() -> None:
    with pytest.raises(ValueError, match="too short"):
        CursorCodec(b"short", ttl_seconds=60)


def test_clamp_limit() -> None:
    assert clamp_limit(None) == DEFAULT_LIMIT
    assert clamp_limit(0) == 1
    assert clamp_limit(-5) == 1
    assert clamp_limit(1000) == MAX_LIMIT
    assert clamp_limit(37) == 37


def test_page_envelope_shape() -> None:
    page = Page[int](data=[1, 2], page=PageInfo(next_cursor="c", has_more=True))
    assert page.model_dump() == {
        "data": [1, 2],
        "page": {"next_cursor": "c", "has_more": True, "reset": False},
    }
