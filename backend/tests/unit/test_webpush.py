"""Web Push encryption, VAPID and delivery (BL-3.16; NOTIF-005, RFC 8291/8292)."""

from __future__ import annotations

import json
import uuid

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.modules.identity.push_tokens import PushTarget
from app.modules.notifications.push import PushMessage
from app.modules.notifications.webpush import (
    Vapid,
    WebPushSender,
    _hkdf,
    _point,
    b64url,
    b64url_decode,
    encrypt,
)


def browser_subscription() -> tuple[ec.EllipticCurvePrivateKey, str, str]:
    """What a browser holds: its key pair and auth secret (p256dh and auth as base64url)."""
    key = ec.generate_private_key(ec.SECP256R1())
    return key, b64url(_point(key.public_key())), b64url(b"0123456789abcdef")


def decrypt(body: bytes, receiver: ec.EllipticCurvePrivateKey, auth: str) -> bytes:
    """The browser's side of RFC 8291."""
    salt, record_size, id_length = body[:16], int.from_bytes(body[16:20], "big"), body[20]
    sender_point = body[21 : 21 + id_length]
    ciphertext = body[21 + id_length :]
    assert record_size == 4096
    sender = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), sender_point)
    shared = receiver.exchange(ec.ECDH(), sender)
    receiver_point = _point(receiver.public_key())
    ikm = _hkdf(
        b64url_decode(auth), shared, b"WebPush: info\x00" + receiver_point + sender_point, 32
    )
    key = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    plain = AESGCM(key).decrypt(nonce, ciphertext, None)
    assert plain.endswith(b"\x02")  # last record
    return plain[:-1]


@pytest.mark.req("NOTIF-005")
def test_payloads_are_encrypted_for_the_subscription_only() -> None:
    receiver, p256dh, auth = browser_subscription()
    body = encrypt(b'{"title": "New message"}', p256dh=p256dh, auth=auth)
    assert b"New message" not in body
    assert decrypt(body, receiver, auth) == b'{"title": "New message"}'
    other, _, _ = browser_subscription()
    with pytest.raises(Exception):  # noqa: B017 - another browser can't read it
        decrypt(body, other, auth)
    assert encrypt(b"x", p256dh=p256dh, auth=auth) != encrypt(b"x", p256dh=p256dh, auth=auth)


def test_vapid_tokens_are_signed_for_the_push_service_origin() -> None:
    private = ec.generate_private_key(ec.SECP256R1())
    scalar = b64url(private.private_numbers().private_value.to_bytes(32, "big"))
    vapid = Vapid(scalar, "mailto:ops@example.com")
    assert vapid.public_key == b64url(_point(private.public_key()))
    header = vapid.header("https://fcm.googleapis.com/fcm/send/abc", now=1_800_000_000)
    token = header.split("t=")[1].split(",")[0]
    assert header.endswith(f"k={vapid.public_key}")
    claims = jwt.decode(
        token,
        private.public_key(),
        algorithms=["ES256"],
        audience="https://fcm.googleapis.com",
        options={"verify_exp": False},
    )
    assert claims["sub"] == "mailto:ops@example.com"


async def test_sender_posts_encrypted_payloads_and_prunes_gone_subscriptions() -> None:
    receiver, p256dh, auth = browser_subscription()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(410 if request.url.path.endswith("/gone") else 201)

    vapid = Vapid(
        b64url(
            ec.generate_private_key(ec.SECP256R1())
            .private_numbers()
            .private_value.to_bytes(32, "big")
        ),
        "mailto:ops@example.com",
    )
    live = PushTarget(uuid.uuid4(), "webpush", "https://push.example/sub/live", p256dh, auth)
    gone = PushTarget(uuid.uuid4(), "webpush", "https://push.example/sub/gone", p256dh, auth)
    expo = PushTarget(uuid.uuid4(), "expo", "ExponentPushToken[x]")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await WebPushSender(http, vapid).send(
            [live, gone, expo],
            PushMessage(
                title="New message", body="Ana sent you a message.", data={"type": "new_message"}
            ),
        )
    assert result == {gone.id}
    assert len(seen) == 2  # the Expo target isn't Web Push's
    first = seen[0]
    assert first.headers["content-encoding"] == "aes128gcm"
    assert first.headers["authorization"].startswith("vapid t=")
    assert first.headers["ttl"] == "86400"
    assert json.loads(decrypt(first.content, receiver, auth))["body"] == "Ana sent you a message."


async def test_rate_limits_and_outages_are_retried() -> None:
    _, p256dh, auth = browser_subscription()
    vapid = Vapid(
        b64url(
            ec.generate_private_key(ec.SECP256R1())
            .private_numbers()
            .private_value.to_bytes(32, "big")
        ),
        "mailto:ops@example.com",
    )
    target = PushTarget(uuid.uuid4(), "webpush", "https://push.example/sub/1", p256dh, auth)
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(429))
    ) as http:
        with pytest.raises(RuntimeError):
            await WebPushSender(http, vapid).send(
                [target], PushMessage(title="t", body="b", data={})
            )


def test_rfc8291_appendix_a_vector() -> None:
    """The worked example from RFC 8291 (Appendix A), byte for byte."""
    sender = ec.derive_private_key(
        int.from_bytes(b64url_decode("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"),
        ec.SECP256R1(),
    )
    body = encrypt(
        b"When I grow up, I want to be a watermelon",
        p256dh="BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
        auth="BTBZMqHH6r4Tts7J_aSIgg",
        sender_key=sender,
        salt=b64url_decode("DGv6ra1nlYgDCS1FRnbzlw"),
    )
    assert b64url(body) == (
        "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
    )
