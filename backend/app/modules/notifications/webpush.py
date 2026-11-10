"""Web Push for the web app (BL-3.16; NOTIF-005, RFC 8030/8291/8292).

- Payloads are encrypted for the browser's subscription (RFC 8291 ``aes128gcm``): an ephemeral
  P-256 key agreement with the subscription's ``p256dh`` and ``auth`` secret, so push services
  only ever see ciphertext.
- Requests carry a VAPID token (RFC 8292, ES256) for the push service's origin.
- ``404``/``410`` mean the subscription is gone: the device is disabled. ``429``/``5xx`` raise so
  the job retries.
"""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from collections.abc import Sequence
from urllib.parse import urlsplit

import httpx
import jwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.modules.identity import service as identity
from app.modules.notifications.push import PushMessage, PushSender

RECORD_SIZE = 4096
TTL_SECONDS = 24 * 3600


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def _point(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )


def encrypt(
    plaintext: bytes,
    *,
    p256dh: str,
    auth: str,
    sender_key: ec.EllipticCurvePrivateKey | None = None,
    salt: bytes | None = None,
) -> bytes:
    """RFC 8291 message body: ``salt ‖ rs ‖ idlen ‖ keyid ‖ ciphertext`` (one record)."""
    receiver_point = b64url_decode(p256dh)
    receiver = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), receiver_point)
    sender_key = sender_key or ec.generate_private_key(ec.SECP256R1())
    sender_point = _point(sender_key.public_key())
    salt = salt or os.urandom(16)
    shared = sender_key.exchange(ec.ECDH(), receiver)
    ikm = _hkdf(
        b64url_decode(auth), shared, b"WebPush: info\x00" + receiver_point + sender_point, 32
    )
    key = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext + b"\x02", None)  # last-record delimiter
    header = salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(sender_point)]) + sender_point
    return header + ciphertext


class Vapid:
    """The application server's key pair (RFC 8292)."""

    def __init__(self, private_key: str, subject: str) -> None:
        raw = private_key.strip()
        if raw.startswith("-----BEGIN"):
            loaded = serialization.load_pem_private_key(raw.encode(), password=None)
            assert isinstance(loaded, ec.EllipticCurvePrivateKey)
            self._key = loaded
        else:  # base64url of the 32-byte private scalar, as web-push tooling prints it
            self._key = ec.derive_private_key(
                int.from_bytes(b64url_decode(raw), "big"), ec.SECP256R1()
            )
        self.subject = subject
        self.public_key = b64url(_point(self._key.public_key()))

    def header(self, endpoint: str, *, now: float | None = None) -> str:
        parts = urlsplit(endpoint)
        claims = {
            "aud": f"{parts.scheme}://{parts.netloc}",
            "exp": int((now or time.time()) + 12 * 3600),
            "sub": self.subject,
        }
        token = jwt.encode(claims, self._key, algorithm="ES256")
        return f"vapid t={token}, k={self.public_key}"


class WebPushSender:
    def __init__(self, http: httpx.AsyncClient, vapid: Vapid) -> None:
        self._http = http
        self._vapid = vapid

    async def send(
        self, targets: Sequence[identity.PushTarget], message: PushMessage
    ) -> set[uuid.UUID]:
        gone: set[uuid.UUID] = set()
        payload = json.dumps(
            {"title": message.title, "body": message.body, "data": message.data}
        ).encode()
        for target in targets:
            if target.provider != "webpush" or not target.webpush_p256dh or not target.webpush_auth:
                continue
            body = encrypt(payload, p256dh=target.webpush_p256dh, auth=target.webpush_auth)
            headers = {
                "Authorization": self._vapid.header(target.token),
                "Content-Encoding": "aes128gcm",
                "Content-Type": "application/octet-stream",
                "TTL": str(TTL_SECONDS),
                "Urgency": "normal",
            }
            if message.collapse_key:
                headers["Topic"] = b64url(message.collapse_key.encode())[:32]
            response = await self._http.post(
                target.token, content=body, headers=headers, timeout=10.0
            )
            if response.status_code in (404, 410):
                gone.add(target.id)
            elif response.status_code == 429 or response.status_code >= 500:
                raise RuntimeError(f"push service answered {response.status_code}")  # retried
        return gone


class RoutingPushSender:
    """Each target goes to its provider's adapter; providers without one are skipped."""

    def __init__(self, senders: dict[str, PushSender]) -> None:
        self._senders = senders

    async def send(
        self, targets: Sequence[identity.PushTarget], message: PushMessage
    ) -> set[uuid.UUID]:
        gone: set[uuid.UUID] = set()
        for provider, sender in self._senders.items():
            mine = [t for t in targets if t.provider == provider]
            if mine:
                gone |= await sender.send(mine, message)
        return gone


def build_sender(
    provider: str,
    http: httpx.AsyncClient,
    *,
    expo_access_token: str | None,
    vapid: Vapid | None,
) -> PushSender | None:
    """``log`` records in memory (dev/test); ``expo`` sends Expo pushes, plus Web Push when VAPID
    keys are configured; ``disabled`` sends nothing."""
    from app.modules.notifications.push import ExpoPushSender, RecordingPushSender

    if provider == "log":
        return RecordingPushSender()
    if provider != "expo":
        return None
    senders: dict[str, PushSender] = {"expo": ExpoPushSender(http, expo_access_token)}
    if vapid is not None:
        senders["webpush"] = WebPushSender(http, vapid)
    return RoutingPushSender(senders)
