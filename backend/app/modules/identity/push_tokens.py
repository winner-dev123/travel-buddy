"""Push device registry (BL-3.06; NOTIF-002, NOTIF-005, docs/04 §3 ``device_push_tokens``).

Native tokens and Web Push endpoints are capability secrets. They are encrypted with AES-256-GCM
under a key derived (HKDF) from the refresh-token derivation secret, deduplicated by SHA-256 and
never logged or returned. A registration belongs to the session that made it: revoking the session
deletes it, and delivery skips revoked sessions in any case.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import DevicePushToken, PushProvider, UserSession

_INFO = b"travelbuddy push token encryption v1"


class PushTokenCipher:
    def __init__(self, secret: str) -> None:
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(
            secret.encode("utf-8")
        )
        self._aead = AESGCM(key)

    def encrypt(self, value: str) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._aead.encrypt(nonce, value.encode("utf-8"), _INFO)

    def decrypt(self, blob: bytes) -> str:
        return self._aead.decrypt(blob[:12], blob[12:], _INFO).decode("utf-8")


def token_hash(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


@dataclass(frozen=True, slots=True)
class PushTarget:
    """A decrypted destination, handed only to push senders."""

    id: uuid.UUID
    provider: str
    token: str
    webpush_p256dh: str | None = None
    webpush_auth: str | None = None


async def register(
    session: AsyncSession,
    cipher: PushTokenCipher,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    provider: str,
    device_id: str,
    token: str,
    p256dh: str | None = None,
    auth: str | None = None,
) -> DevicePushToken:
    """Register or refresh: one row per device of the user, and a token belongs to one row
    (a phone signed in again by someone else moves to the new account)."""
    digest = token_hash(token)
    await session.execute(
        delete(DevicePushToken).where(
            or_(
                DevicePushToken.token_hash == digest,
                (DevicePushToken.user_id == user_id) & (DevicePushToken.device_id == device_id),
            )
        )
    )
    row = DevicePushToken(
        user_id=user_id,
        session_id=session_id,
        provider=provider,
        token_ciphertext=cipher.encrypt(token),
        token_hash=digest,
        webpush_p256dh=cipher.encrypt(p256dh) if p256dh else None,
        webpush_auth=cipher.encrypt(auth) if auth else None,
        device_id=device_id,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def unregister(
    session: AsyncSession, *, user_id: uuid.UUID, device_token_id: uuid.UUID
) -> bool:
    result = await session.execute(
        delete(DevicePushToken).where(
            DevicePushToken.id == device_token_id, DevicePushToken.user_id == user_id
        )
    )
    return bool(getattr(result, "rowcount", 0))


async def delete_for_sessions(session: AsyncSession, session_ids: Sequence[uuid.UUID]) -> None:
    if session_ids:
        await session.execute(
            delete(DevicePushToken).where(DevicePushToken.session_id.in_(set(session_ids)))
        )


async def targets(
    session: AsyncSession, cipher: PushTokenCipher, user_id: uuid.UUID
) -> list[PushTarget]:
    """Live destinations: enabled, on a session that is neither revoked nor expired."""
    rows = await session.scalars(
        select(DevicePushToken)
        .join(UserSession, UserSession.id == DevicePushToken.session_id)
        .where(
            DevicePushToken.user_id == user_id,
            DevicePushToken.disabled_at.is_(None),
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > func.now(),
        )
    )
    return [
        PushTarget(
            id=row.id,
            provider=row.provider,
            token=cipher.decrypt(row.token_ciphertext),
            webpush_p256dh=cipher.decrypt(row.webpush_p256dh) if row.webpush_p256dh else None,
            webpush_auth=cipher.decrypt(row.webpush_auth) if row.webpush_auth else None,
        )
        for row in rows
    ]


async def disable(session: AsyncSession, ids: Sequence[uuid.UUID]) -> None:
    """The provider said these destinations are gone (e.g. Expo ``DeviceNotRegistered``)."""
    if ids:
        await session.execute(
            update(DevicePushToken)
            .where(DevicePushToken.id.in_(set(ids)))
            .values(disabled_at=func.now())
        )


async def purge(session: AsyncSession) -> int:
    """Tokens of revoked sessions, and tokens disabled more than 30 days ago."""
    revoked = select(UserSession.id).where(UserSession.revoked_at.is_not(None))
    result = await session.execute(
        delete(DevicePushToken).where(
            or_(
                DevicePushToken.session_id.in_(revoked),
                DevicePushToken.disabled_at < func.now() - func.make_interval(0, 0, 0, 30),
            )
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


__all__ = [
    "PushProvider",
    "PushTarget",
    "PushTokenCipher",
    "datetime",
]
