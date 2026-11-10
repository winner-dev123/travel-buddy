"""Realtime frames (docs/06 §3-4; contracts/realtime): envelope, client payloads, limits."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.ids import uuid7
from app.modules.messaging.schemas import SendMessageRequest

PROTOCOL: Final = "travelbuddy.v1"
MAX_INBOUND_BYTES: Final = 32 * 1024
HEARTBEAT_INTERVAL_S: Final = 25
TYPING_INTERVAL_S: Final = 3
TYPING_TTL_S: Final = 8
FRAMES_PER_MINUTE: Final = 120
MESSAGES_PER_MINUTE: Final = 30
MAX_INVALID_FRAMES: Final = 5
SEQ_MAX: Final = 9007199254740991

# contracts/realtime/envelope.schema.json#/$defs/RealtimeErrorCode
ERROR_CODES: Final = frozenset(
    {
        "bad_frame",
        "unsupported_version",
        "unknown_type",
        "validation_failed",
        "unauthenticated",
        "token_expired",
        "token_invalid",
        "ticket_invalid",
        "session_revoked",
        "account_suspended",
        "origin_not_allowed",
        "auth_timeout",
        "not_found",
        "forbidden",
        "connection_required",
        "member_restricted",
        "chat_admins_only",
        "message_edit_window_expired",
        "media_not_ready",
        "media_rejected",
        "payload_too_large",
        "rate_limited",
        "conflict",
        "service_unavailable",
        "internal_error",
    }
)

LIMITS: Final = {
    "max_inbound_frame_bytes": MAX_INBOUND_BYTES,
    "message_send_per_minute": MESSAGES_PER_MINUTE,
    "typing_min_interval_s": TYPING_INTERVAL_S,
    "frames_per_minute": FRAMES_PER_MINUTE,
}


def timestamp(value: datetime | None = None) -> str:
    return (value or datetime.now(tz=UTC)).astimezone(UTC).isoformat().replace("+00:00", "Z")


def frame(kind: str, data: dict[str, Any], *, reply_to: uuid.UUID | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "v": 1,
        "type": kind,
        "id": str(uuid7()),
        "ts": timestamp(),
        "data": data,
    }
    if reply_to is not None:
        out["reply_to"] = str(reply_to)
    return out


def error_code(code: str, status: int) -> str:
    """Map a platform error code onto the realtime subset."""
    if code in ERROR_CODES:
        return code
    if status == 404:
        return "not_found"
    if status == 409:
        return "conflict"
    if status == 422:
        return "validation_failed"
    if status == 429:
        return "rate_limited"
    if status == 503:
        return "service_unavailable"
    if status in (401, 403):
        return "forbidden"
    return "internal_error"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Envelope(_Strict):
    """A client frame. ``reply_to`` is for server frames only, so ``extra=forbid`` rejects it."""

    v: int
    type: str = Field(pattern=r"^[a-z]+(\.[a-z_]+)*$", max_length=64)
    id: uuid.UUID
    ts: datetime
    data: dict[str, Any] = Field(default_factory=dict)


class AuthData(_Strict):
    access_token: str | None = Field(default=None, min_length=20, max_length=4096)
    ticket: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{43}$")
    client: Literal["ios", "android", "web"] | None = None
    app_version: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        if (self.access_token is None) == (self.ticket is None):
            raise ValueError("send exactly one of access_token or ticket")
        return self


class SendData(SendMessageRequest):
    conversation_id: uuid.UUID

    def request(self) -> SendMessageRequest:
        return SendMessageRequest.model_validate(self.model_dump(exclude={"conversation_id"}))


class EditData(_Strict):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    body: str = Field(min_length=1, max_length=4000)


class DeleteData(_Strict):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    reason_code: str | None = Field(default=None, max_length=40)


class ReadData(_Strict):
    conversation_id: uuid.UUID
    read_through_seq: int = Field(ge=0, le=SEQ_MAX)


class DeliveredData(_Strict):
    conversation_id: uuid.UUID
    delivered_through_seq: int = Field(ge=0, le=SEQ_MAX)


class TypingData(_Strict):
    conversation_id: uuid.UUID


class SyncEntry(_Strict):
    conversation_id: uuid.UUID
    last_seq: int = Field(ge=0, le=SEQ_MAX)


class SyncData(_Strict):
    conversations: list[SyncEntry] = Field(max_length=500)
    conversation_list_synced_at: datetime | None = None


class PingData(_Strict):
    pass
