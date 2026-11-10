"""``/v1/realtime``: the WebSocket gateway (BL-3.04; docs/06).

Every mutation runs the same messaging service as REST and is committed before any ack or fanout
(DM-003/004). The socket only delivers: holding one grants nothing, and each send, edit, delete,
receipt and typing frame is re-authorized by the service. Events reach a connection through the
user's channel on the realtime bus; message frames are loaded for the receiving user at delivery
time, so access is checked again then.

Browsers authenticate with single-use tickets (``auth {ticket}``, ADR-0013). Not here yet:
``notification.new`` frames.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, WebSocket
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.ids import uuid7
from app.core.ratelimit import RateLimiter
from app.core.security.access_tokens import AccessTokenService
from app.core.security.authn import principal_from_claims
from app.core.security.principal import AccountStatus, PlatformRole, Principal
from app.core.time import Clock
from app.modules.identity import service as identity
from app.modules.messaging.schemas import UpdateReceiptsRequest
from app.modules.messaging.service import MessagingService
from app.realtime.bus import RealtimeBus, Subscription
from app.realtime.frames import (
    FRAMES_PER_MINUTE,
    HEARTBEAT_INTERVAL_S,
    LIMITS,
    MAX_INBOUND_BYTES,
    MAX_INVALID_FRAMES,
    PROTOCOL,
    TYPING_INTERVAL_S,
    TYPING_TTL_S,
    AuthData,
    DeleteData,
    DeliveredData,
    EditData,
    Envelope,
    PingData,
    ReadData,
    SendData,
    SyncData,
    TypingData,
    error_code,
    frame,
    timestamp,
)

logger = logging.getLogger(__name__)

router = APIRouter()

EXPIRY_NOTICE = timedelta(seconds=60)
TICKET_REAUTH_AFTER = timedelta(minutes=15)
_ROLES = frozenset(role.value for role in PlatformRole)


@router.websocket("/v1/realtime")
async def realtime(websocket: WebSocket) -> None:
    await Connection(websocket).run()


class _ClosedError(Exception):
    """The socket is gone (or we closed it); stop handling this connection."""


class Connection:
    def __init__(self, websocket: WebSocket) -> None:
        state = websocket.app.state
        self.ws = websocket
        self.settings: Settings = state.settings
        self.tokens: AccessTokenService = state.access_tokens
        self.messaging: MessagingService = state.messaging_service
        self.bus: RealtimeBus = state.realtime_bus
        self.limiter: RateLimiter | None = state.rate_limiter
        self.clock: Clock = state.clock
        self.connection_id = uuid7()
        self.principal: Principal | None = None
        self.expires_at: datetime | None = None
        self.invalid_frames = 0
        self.recent_frames: deque[float] = deque()
        self.typing_sent: dict[uuid.UUID, float] = {}
        self.send_lock = asyncio.Lock()
        self.closed = False

    # ─────────────────────────────── lifecycle ───────────────────────────────

    async def run(self) -> None:
        if PROTOCOL not in (self.ws.scope.get("subprotocols") or []):
            await self.ws.accept()
            await self._close(4010)
            return
        await self.ws.accept(subprotocol=PROTOCOL)
        origin = self.ws.headers.get("origin")
        if origin is not None and origin not in self.settings.cors_allowed_origins:
            await self._auth_error("origin_not_allowed", "This origin is not allowed.", 4005)
            return
        try:
            first = await asyncio.wait_for(
                self._receive(), timeout=self.settings.realtime_auth_timeout_seconds
            )
        except TimeoutError:
            await self._auth_error("auth_timeout", "Authenticate first.", 4002)
            return
        except _ClosedError:
            return
        if first.type != "auth" or not await self._authenticate(first):
            await self._close(4001)
            return
        assert self.principal is not None
        subscription = await self.bus.subscribe(self.principal.user_id)
        tasks = [
            asyncio.create_task(self._pump(subscription)),
            asyncio.create_task(self._watch_expiry()),
        ]
        try:
            await self._serve()
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(BaseException):
                    await task
            await subscription.close()

    async def _serve(self) -> None:
        while not self.closed:
            try:
                envelope = await asyncio.wait_for(
                    self._receive(), timeout=self.settings.realtime_idle_timeout_seconds
                )
            except TimeoutError:
                await self._close(1000)
                return
            except _ClosedError:
                return
            if not await self._within_frame_limit(envelope):
                continue
            await self._dispatch(envelope)

    async def _receive(self) -> Envelope:
        message = await self.ws.receive()
        if message["type"] == "websocket.disconnect":
            self.closed = True
            raise _ClosedError
        if message.get("bytes") is not None:
            await self._close(4000)
            raise _ClosedError
        text = message.get("text") or ""
        if len(text.encode("utf-8")) > MAX_INBOUND_BYTES:
            await self._close(1009)
            raise _ClosedError
        try:
            raw = json.loads(text)
        except ValueError:
            await self._close(4000)
            raise _ClosedError from None
        if not isinstance(raw, dict):
            await self._close(4000)
            raise _ClosedError
        if raw.get("v") != 1:
            await self._send(
                frame(
                    "error",
                    {
                        "code": "unsupported_version",
                        "message": "Protocol version 1 only.",
                        "retryable": False,
                    },
                )
            )
            await self._close(4010)
            raise _ClosedError
        try:
            return Envelope.model_validate(raw)
        except ValidationError:
            await self._close(4000)
            raise _ClosedError from None

    async def _send(self, payload: dict[str, Any]) -> None:
        if self.closed:
            return
        async with self.send_lock:
            try:
                await self.ws.send_text(json.dumps(payload, default=str))
            except Exception:  # the peer went away; the receive loop will notice
                self.closed = True

    async def _close(self, code: int) -> None:
        if self.closed:
            return
        self.closed = True
        with contextlib.suppress(Exception):
            await self.ws.close(code)

    # ─────────────────────────────── auth ───────────────────────────────

    async def _auth_error(
        self, code: str, message: str, close_code: int, reply_to: uuid.UUID | None = None
    ) -> None:
        await self._send(
            frame(
                "auth.error",
                {"code": code, "message": message, "close_code": close_code},
                reply_to=reply_to,
            )
        )
        await self._close(close_code)

    async def _authenticate(self, envelope: Envelope) -> bool:
        """First auth, or in-band re-auth for the same user and session (docs/06 §5.2)."""
        try:
            data = AuthData.model_validate(envelope.data)
        except ValidationError:
            await self._auth_error("unauthenticated", "Send an access token.", 4001, envelope.id)
            return False
        if data.ticket is not None:
            authenticated = await self._from_ticket(data.ticket)
            if authenticated is None:
                await self._auth_error("ticket_invalid", "Get a new ticket.", 4001, envelope.id)
                return False
            principal, expires_at = authenticated
        else:
            assert data.access_token is not None
            try:
                claims = self.tokens.verify(data.access_token)
            except AppError as exc:
                code = "token_expired" if exc.code is ErrorCode.TOKEN_EXPIRED else "token_invalid"
                await self._auth_error(code, "Sign in again.", 4001, envelope.id)
                return False
            principal, expires_at = principal_from_claims(claims), claims.expires_at
        if self.principal is not None and (
            principal.user_id != self.principal.user_id
            or principal.session_id != self.principal.session_id
        ):
            await self._auth_error(
                "unauthenticated", "Re-authenticate with the same session.", 4001, envelope.id
            )
            return False
        self.principal = principal
        self.expires_at = expires_at
        await self._send(
            frame(
                "auth.ok",
                {
                    "user_id": str(principal.user_id),
                    "session_id": str(principal.session_id),
                    "connection_id": str(self.connection_id),
                    "server_time": timestamp(self.clock.now()),
                    "auth_expires_at": timestamp(expires_at),
                    "heartbeat_interval_s": HEARTBEAT_INTERVAL_S,
                    "limits": dict(LIMITS),
                },
                reply_to=envelope.id,
            )
        )
        return True

    async def _from_ticket(self, ticket: str) -> tuple[Principal, datetime] | None:
        """Browsers authenticate with a single-use ticket from the BFF (ADR-0013); the connection
        must prove the session again 15 minutes after the ticket was issued (docs/06 §5.2)."""
        async with self.ws.app.state.database.sessionmaker() as session, session.begin():
            grant = await identity.consume_realtime_ticket(session, ticket, now=self.clock.now())
        if grant is None:
            return None
        claims = grant.claims
        principal = Principal(
            user_id=grant.user_id,
            session_id=grant.session_id,
            account_status=AccountStatus.ACTIVE,
            roles=frozenset(PlatformRole(r) for r in claims.get("roles", []) if r in _ROLES),
            email_verified=bool(claims.get("email_verified")),
            age_assured=bool(claims.get("age_assured")),
            amr=frozenset(claims.get("amr", [])),
            auth_time=datetime.fromisoformat(claims["auth_time"])
            if claims.get("auth_time")
            else None,
        )
        return principal, grant.issued_at + TICKET_REAUTH_AFTER

    async def _watch_expiry(self) -> None:
        """``auth.expiring`` 60 s before expiry; close ``4001`` if no re-auth arrives in time."""
        warned_for: datetime | None = None
        while not self.closed:
            assert self.expires_at is not None
            expires_at = self.expires_at
            remaining = (expires_at - self.clock.now()).total_seconds()
            if remaining <= 0:
                await self._close(4001)
                return
            if remaining <= EXPIRY_NOTICE.total_seconds() and warned_for != expires_at:
                warned_for = expires_at
                await self._send(
                    frame(
                        "auth.expiring",
                        {"expires_at": timestamp(expires_at), "accepts": ["access_token"]},
                    )
                )
            until_notice = remaining - EXPIRY_NOTICE.total_seconds()
            wait = until_notice if warned_for != expires_at and until_notice > 0 else remaining
            await asyncio.sleep(min(max(wait, 0.05), 30.0))

    # ─────────────────────────────── inbound ───────────────────────────────

    async def _within_frame_limit(self, envelope: Envelope) -> bool:
        now = time.monotonic()
        while self.recent_frames and now - self.recent_frames[0] > 60:
            self.recent_frames.popleft()
        self.recent_frames.append(now)
        if len(self.recent_frames) <= FRAMES_PER_MINUTE:
            return True
        if len(self.recent_frames) > 2 * FRAMES_PER_MINUTE:
            await self._close(4008)
            return False
        retry = int((60 - (now - self.recent_frames[0])) * 1000)
        await self._send(
            frame(
                "rate_limited",
                {"scope": "frames", "retry_after_ms": max(retry, 0)},
                reply_to=envelope.id,
            )
        )
        return False

    async def _dispatch(self, envelope: Envelope) -> None:
        handlers: dict[str, tuple[type[BaseModel], Callable[[Envelope, Any], Awaitable[None]]]] = {
            "ping": (PingData, self._on_ping),
            "auth": (AuthData, self._on_reauth),
            "message.send": (SendData, self._on_send),
            "message.edit": (EditData, self._on_edit),
            "message.delete": (DeleteData, self._on_delete),
            "receipt.read": (ReadData, self._on_read),
            "receipt.delivered": (DeliveredData, self._on_delivered),
            "typing.start": (TypingData, self._on_typing_start),
            "typing.stop": (TypingData, self._on_typing_stop),
            "sync.request": (SyncData, self._on_sync),
        }
        handler = handlers.get(envelope.type)
        if handler is None:
            await self._error(envelope, "unknown_type", f"Unknown frame type {envelope.type}.")
            return
        model, run = handler
        try:
            data = model.model_validate(envelope.data) if envelope.type != "auth" else envelope
        except ValidationError:
            self.invalid_frames += 1
            if self.invalid_frames >= MAX_INVALID_FRAMES:
                await self._close(4000)
                return
            await self._error(envelope, "validation_failed", "The frame is not valid.")
            return
        conversation_id = getattr(data, "conversation_id", None)
        try:
            await run(envelope, data)
        except AppError as exc:
            if exc.code is ErrorCode.RATE_LIMITED:
                await self._rate_limited(envelope, "message_send", 60_000, data)
                return
            await self._error(
                envelope,
                error_code(exc.code.value, exc.status),
                exc.detail or exc.code.value,
                conversation_id=conversation_id,
                client_message_id=getattr(data, "client_message_id", None),
                retryable=exc.status >= 500,
            )
        except Exception:
            logger.exception("realtime_frame_failed", extra={"type": envelope.type})
            await self._error(envelope, "internal_error", "Something went wrong.", retryable=True)

    async def _error(
        self,
        envelope: Envelope,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        conversation_id: uuid.UUID | None = None,
        client_message_id: uuid.UUID | None = None,
    ) -> None:
        data: dict[str, Any] = {"code": code, "message": message, "retryable": retryable}
        if conversation_id is not None:
            data["conversation_id"] = str(conversation_id)
        if client_message_id is not None:
            data["client_message_id"] = str(client_message_id)
        await self._send(frame("error", data, reply_to=envelope.id))

    async def _rate_limited(
        self, envelope: Envelope, scope: str, retry_after_ms: int, data: Any = None
    ) -> None:
        payload: dict[str, Any] = {"scope": scope, "retry_after_ms": retry_after_ms}
        client_message_id = getattr(data, "client_message_id", None)
        if client_message_id is not None:
            payload["client_message_id"] = str(client_message_id)
        await self._send(frame("rate_limited", payload, reply_to=envelope.id))

    @property
    def _me(self) -> Principal:
        assert self.principal is not None
        return self.principal

    async def _on_ping(self, envelope: Envelope, _: PingData) -> None:
        await self._send(frame("pong", {"server_time": timestamp(self.clock.now())}))

    async def _on_reauth(self, envelope: Envelope, _: Envelope) -> None:
        if not await self._authenticate(envelope):
            await self._close(4001)

    async def _on_send(self, envelope: Envelope, data: SendData) -> None:
        if self.limiter is not None:
            decision = await self.limiter.check(
                self.limiter.policy.bucket("message"), f"u:{self._me.user_id}"
            )
            if not decision.allowed:
                await self._rate_limited(
                    envelope, "message_send", decision.retry_after_seconds * 1000, data
                )
                return
        message, duplicate = await self.messaging.send(
            self._me, data.conversation_id, data.request()
        )
        await self._send(
            frame(
                "message.ack",
                {
                    "conversation_id": str(message.conversation_id),
                    "client_message_id": str(data.client_message_id),
                    "message_id": str(message.id),
                    "seq": message.seq,
                    "created_at": timestamp(message.created_at),
                    "duplicate": duplicate,
                },
                reply_to=envelope.id,
            )
        )

    async def _on_edit(self, envelope: Envelope, data: EditData) -> None:
        await self.messaging.edit(
            self._me.user_id, data.conversation_id, data.message_id, data.body
        )

    async def _on_delete(self, envelope: Envelope, data: DeleteData) -> None:
        await self.messaging.delete(
            self._me.user_id, data.conversation_id, data.message_id, reason_code=data.reason_code
        )

    async def _on_read(self, envelope: Envelope, data: ReadData) -> None:
        await self.messaging.update_receipts(
            self._me.user_id,
            data.conversation_id,
            UpdateReceiptsRequest(read_through_seq=data.read_through_seq),
        )

    async def _on_delivered(self, envelope: Envelope, data: DeliveredData) -> None:
        await self.messaging.update_receipts(
            self._me.user_id,
            data.conversation_id,
            UpdateReceiptsRequest(delivered_through_seq=data.delivered_through_seq),
        )

    async def _typing(self, data: TypingData, state: str) -> None:
        recipients = await self.messaging.typing_recipients(self._me.user_id, data.conversation_id)
        expires_at = self.clock.now() + timedelta(seconds=TYPING_TTL_S)
        await self.bus.publish(
            recipients,
            {
                "type": "typing",
                "data": {
                    "conversation_id": str(data.conversation_id),
                    "user_id": str(self._me.user_id),
                    "state": state,
                    "expires_at": timestamp(expires_at),
                },
            },
        )

    async def _on_typing_start(self, envelope: Envelope, data: TypingData) -> None:
        now = time.monotonic()
        last = self.typing_sent.get(data.conversation_id)
        if last is not None and now - last < TYPING_INTERVAL_S:
            return  # silently dropped (docs/06 §10)
        self.typing_sent[data.conversation_id] = now
        await self._typing(data, "started")

    async def _on_typing_stop(self, envelope: Envelope, data: TypingData) -> None:
        self.typing_sent.pop(data.conversation_id, None)
        await self._typing(data, "stopped")

    async def _on_sync(self, envelope: Envelope, data: SyncData) -> None:
        behind = await self.messaging.sync(
            self._me.user_id,
            [(entry.conversation_id, entry.last_seq) for entry in data.conversations],
            list_synced_at=data.conversation_list_synced_at,
        )
        await self._send(
            frame(
                "sync.required",
                {
                    "reason": "reconnect",
                    "full_resync": False,
                    "conversations": [
                        {"conversation_id": str(c), "from_seq": start, "server_last_seq": last}
                        for c, start, last in behind
                    ],
                },
                reply_to=None,
            )
        )

    # ─────────────────────────────── outbound ───────────────────────────────

    async def _pump(self, subscription: Subscription) -> None:
        while not self.closed:
            event = await subscription.get()
            try:
                rendered = await self._render(event)
            except Exception:
                logger.exception("realtime_render_failed", extra={"type": event.get("type")})
                continue
            if rendered is not None:
                await self._send(rendered)
            if event.get("type") == "session.revoked":
                await self._close(4003)
                return

    async def _render(self, event: dict[str, Any]) -> dict[str, Any] | None:
        kind = str(event.get("type"))
        data: dict[str, Any] = dict(event.get("data") or {})
        if kind in ("message.new", "message.updated"):
            try:
                message = await self.messaging.get_message(
                    self._me.user_id,
                    uuid.UUID(str(data["conversation_id"])),
                    uuid.UUID(str(data["message_id"])),
                )
            except AppError:
                return None  # no longer visible to this user (cleared, left, removed)
            payload: dict[str, Any] = {"message": message.model_dump(mode="json")}
            if kind == "message.updated":
                payload["change"] = data.get("change", "edited")
            return frame(kind, payload)
        if kind == "session.revoked" and data.get("session_id") not in (
            None,
            str(self._me.session_id),
        ):
            return None
        data.pop("session_id", None) if kind == "session.revoked" else None
        return frame(kind, data)
