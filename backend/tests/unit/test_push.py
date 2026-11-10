"""Push pieces without a database (BL-3.06): quiet hours, token cipher, Expo adapter."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest

from app.modules.identity.push_tokens import PushTarget, PushTokenCipher, token_hash
from app.modules.notifications.domain import in_quiet_hours
from app.modules.notifications.push import EXPO_PUSH_URL, ExpoPushSender, PushMessage


@pytest.mark.req("NOTIF-003")
@pytest.mark.parametrize(
    ("now", "start", "end", "quiet"),
    [
        ("23:30", "22:00", "07:00", True),
        ("06:59", "22:00", "07:00", True),
        ("07:00", "22:00", "07:00", False),
        ("12:00", "22:00", "07:00", False),
        ("13:00", "12:30", "14:00", True),
        ("14:00", "12:30", "14:00", False),
    ],
)
def test_quiet_hours_window(now: str, start: str, end: str, quiet: bool) -> None:
    hours, minutes = now.split(":")
    assert in_quiet_hours(int(hours) * 60 + int(minutes), start, end) is quiet


def test_token_cipher_round_trips_and_hides_the_token() -> None:
    cipher = PushTokenCipher("s" * 40)
    blob = cipher.encrypt("ExponentPushToken[abc]")
    assert b"ExponentPushToken" not in blob
    assert cipher.decrypt(blob) == "ExponentPushToken[abc]"
    assert cipher.encrypt("x") != cipher.encrypt("x")  # random nonce
    with pytest.raises(Exception):  # noqa: B017 - any authentication failure
        PushTokenCipher("t" * 40).decrypt(blob)
    assert token_hash("a") == token_hash("a") != token_hash("b")


async def test_expo_sender_batches_and_reports_unregistered_devices() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == EXPO_PUSH_URL
        assert request.headers["authorization"] == "Bearer token-1"
        body = json.loads(request.content)
        seen.extend(body)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"status": "ok", "id": "1"},
                    {"status": "error", "details": {"error": "DeviceNotRegistered"}},
                ]
            },
        )

    alive = PushTarget(id=uuid.uuid4(), provider="expo", token="ExponentPushToken[a]")
    gone = PushTarget(id=uuid.uuid4(), provider="expo", token="ExponentPushToken[b]")
    web = PushTarget(id=uuid.uuid4(), provider="webpush", token="https://push.example/x")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        sender = ExpoPushSender(http, "token-1")
        result = await sender.send(
            [alive, gone, web],
            PushMessage(title="New message", body="Ana sent you a message.", data={"type": "x"}),
        )
    assert result == {gone.id}
    assert [m["to"] for m in seen] == [alive.token, gone.token]  # Web Push is not Expo's
    assert seen[0]["title"] == "New message"


async def test_expo_server_errors_are_retried_by_the_job() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(503))
    ) as http:
        sender = ExpoPushSender(http)
        target = PushTarget(id=uuid.uuid4(), provider="expo", token="ExponentPushToken[a]")
        with pytest.raises(RuntimeError):
            await sender.send([target], PushMessage(title="t", body="b", data={}))
