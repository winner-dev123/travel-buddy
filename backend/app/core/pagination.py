"""Cursor pagination: opaque, HMAC-signed, scope-bound, expiring cursors.

Cursors are *signed, not encrypted*: never place sensitive data in a cursor payload. The scope
binds a cursor to one endpoint + filter set so it cannot be replayed elsewhere.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import AppError, ErrorCode

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
MAX_CURSOR_LENGTH = 2048
_CURSOR_VERSION = 1
_SIGNATURE_BYTES = 16
_CLOCK_SKEW_SECONDS = 60


class PageInfo(BaseModel):
    """Contract ``PageInfo``: cursor lists (destinations, comments, ...)."""

    model_config = ConfigDict(frozen=True)

    next_cursor: str | None = None
    has_more: bool = False


class FeedPageInfo(PageInfo):
    """Contract ``FeedPageInfo``: ranked lists whose snapshot can expire."""

    reset: bool = Field(
        default=False,
        description="True when the server discarded an expired snapshot and restarted the list.",
    )


class Page[T](BaseModel):
    """Standard list envelope: ``{"data": [...], "page": {...}}``."""

    data: list[T]
    page: PageInfo


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _invalid(detail: str) -> AppError:
    return AppError(ErrorCode.INVALID_CURSOR, detail)


class CursorCodec:
    def __init__(
        self,
        key: bytes,
        *,
        ttl_seconds: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if len(key) < 16:
            raise ValueError("cursor signing key too short")
        self._key = key
        self._ttl = ttl_seconds
        self._clock = clock

    def _sign(self, raw: bytes) -> bytes:
        return hmac.new(self._key, raw, hashlib.sha256).digest()[:_SIGNATURE_BYTES]

    def encode(self, payload: Mapping[str, Any], *, scope: str) -> str:
        body = {"v": _CURSOR_VERSION, "s": scope, "iat": int(self._clock()), "p": dict(payload)}
        raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
        token = f"{_b64encode(raw)}.{_b64encode(self._sign(raw))}"
        if len(token) > MAX_CURSOR_LENGTH:
            raise ValueError("cursor payload too large")
        return token

    def decode(self, token: str, *, scope: str) -> dict[str, Any]:
        if not token or len(token) > MAX_CURSOR_LENGTH or token.count(".") != 1:
            raise _invalid("Malformed cursor.")
        body_part, sig_part = token.split(".")
        try:
            raw = _b64decode(body_part)
            signature = _b64decode(sig_part)
        except (binascii.Error, ValueError) as exc:
            raise _invalid("Malformed cursor.") from exc
        if not hmac.compare_digest(signature, self._sign(raw)):
            raise _invalid("Cursor signature mismatch.")
        try:
            body = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise _invalid("Malformed cursor.") from exc
        if not isinstance(body, dict) or body.get("v") != _CURSOR_VERSION:
            raise _invalid("Unsupported cursor version.")
        if body.get("s") != scope:
            raise _invalid("Cursor does not belong to this listing.")
        issued_at = body.get("iat")
        now = self._clock()
        if not isinstance(issued_at, int) or issued_at > now + _CLOCK_SKEW_SECONDS:
            raise _invalid("Cursor timestamp invalid.")
        if now - issued_at > self._ttl:
            raise _invalid("Cursor expired; restart the listing.")
        payload = body.get("p")
        if not isinstance(payload, dict):
            raise _invalid("Malformed cursor.")
        return payload


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    return max(1, min(MAX_LIMIT, limit))
