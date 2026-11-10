"""Push devices and delivery end to end (BL-3.06; NOTIF-002..005, DM-009)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.time import FixedClock
from app.main import create_app
from app.modules.notifications.push import RecordingPushSender
from app.modules.notifications.webpush import _point, b64url
from tests.conftest import make_identity_settings, make_settings
from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_messaging import _pair, _sent
from tests.integration.test_posts import CRON, _problem, _tick, _user, app  # noqa: F401

pytestmark = pytest.mark.integration


def _sender(live: LiveApp) -> RecordingPushSender:
    sender = live.client.app.state.push_sender  # type: ignore[attr-defined]
    assert isinstance(sender, RecordingPushSender)
    return sender


def _register(live: LiveApp, token: str, push_token: str, device: str | None = None) -> Any:
    return live.client.post(
        "/v1/users/me/devices",
        headers=_auth(token),
        json={"provider": "expo", "token": push_token, "device_id": device or uuid.uuid4().hex},
    )


def _expo_token() -> str:
    return f"ExponentPushToken[{uuid.uuid4().hex[:22]}]"


def _pushes_to(live: LiveApp, push_token: str) -> list[Any]:
    return [message for target, message in _sender(live).sent if target.token == push_token]


def _deliver(live: LiveApp) -> None:
    _tick(live)  # event → notification (+ push job)
    _tick(live)  # push job


@pytest.mark.req("NOTIF-002", "NOTIF-005")
def test_device_registry_keeps_tokens_secret_and_one_row_per_device(app: LiveApp) -> None:  # noqa: F811
    token, user_id = _user(app)
    first = _expo_token()
    registered = _register(app, token, first, "device-0001")
    assert registered.status_code == 201, registered.text
    assert_matches_contract(registered.json(), "PushDevice")
    assert first not in registered.text  # never returned
    assert (
        db_scalar(
            app.db_url,
            "SELECT count(*) FROM device_push_tokens "
            "WHERE position(CAST(:t AS bytea) in token_ciphertext) > 0",
            t=first.encode(),
        )
        == 0
    )  # stored encrypted

    second = _expo_token()
    again = _register(app, token, second, "device-0001")  # the same device refreshed its token
    assert again.status_code == 201
    count = db_scalar(
        app.db_url,
        "SELECT count(*) FROM device_push_tokens WHERE user_id = :u",
        u=uuid.UUID(user_id),
    )
    assert count == 1

    web = app.client.post(
        "/v1/users/me/devices",
        headers=_auth(token),
        json={
            "provider": "webpush",
            "device_id": "browser-0001",
            "subscription": {
                "endpoint": "https://push.example/endpoint/secret",
                "expiration_time": None,
                "keys": {"p256dh": "BKey", "auth": "AuthKey"},
            },
        },
    )
    assert web.status_code == 201, web.text
    assert "push.example" not in web.text

    other, _ = _user(app)
    url = f"/v1/users/me/devices/{web.json()['id']}"
    _problem(app.client.delete(url, headers=_auth(other)), 404, "not_found")
    assert app.client.delete(url, headers=_auth(token)).status_code == 204
    assert (
        app.client.post(
            "/v1/users/me/devices",
            headers=_auth(token),
            json={"provider": "carrier-pigeon", "token": "x" * 10, "device_id": "d" * 8},
        ).status_code
        == 422
    )


@pytest.mark.req("NOTIF-002", "NOTIF-004", "DM-009")
def test_new_messages_push_without_their_content(app: LiveApp) -> None:  # noqa: F811
    ana, ana_id, bo, _, conversation = _pair(app)
    push_token = _expo_token()
    assert _register(app, bo, push_token).status_code == 201
    _sent(app, ana, conversation, "My door code is 4321")
    _deliver(app)
    [message] = _pushes_to(app, push_token)
    assert "4321" not in message.title + message.body + str(message.data)
    assert message.data["type"] == "new_message"
    assert message.data["entity_id"] == conversation
    assert message.collapse_key == f"new_message:{conversation}"
    pushed = db_scalar(
        app.db_url,
        "SELECT count(*) FROM notifications WHERE type = 'new_message' AND pushed_at IS NOT NULL "
        "AND actor_id = :a",
        a=uuid.UUID(ana_id),
    )
    assert pushed == 1


@pytest.mark.req("NOTIF-002", "NOTIF-003")
def test_push_respects_type_preferences_quiet_hours_and_sessions(app: LiveApp) -> None:  # noqa: F811
    ana, ana_id = _user(app)
    bo, bo_id = _user(app)
    push_token = _expo_token()
    assert _register(app, bo, push_token).status_code == 201

    def follow(follower: str) -> None:
        response = app.client.put(f"/v1/users/{bo_id}/follow", headers=_auth(follower))
        assert response.status_code in (200, 201), response.text

    # Push off for new followers: the in-app notification still arrives.
    off = app.client.patch(
        "/v1/users/me/preferences",
        headers=_auth(bo),
        json={"notification_settings": {"new_follower": {"push": False}}},
    )
    assert off.status_code == 200, off.text
    follow(ana)
    _deliver(app)
    assert _pushes_to(app, push_token) == []
    inbox = app.client.get("/v1/notifications", headers=_auth(bo)).json()["data"]
    assert [n["type"] for n in inbox] == ["new_follower"]

    # Quiet hours all day long hold pushes back.
    _problem(
        app.client.patch(
            "/v1/users/me/preferences",
            headers=_auth(bo),
            json={"quiet_hours": {"start": "22:00", "end": "22:00"}},
        ),
        422,
        "validation_failed",
    )
    quiet = app.client.patch(
        "/v1/users/me/preferences",
        headers=_auth(bo),
        json={
            "notification_settings": {"new_follower": {"push": True}},
            "quiet_hours": {"start": "00:00", "end": "23:59"},
        },
    )
    assert quiet.status_code == 200, quiet.text
    assert_matches_contract(quiet.json(), "Preferences")
    assert quiet.json()["quiet_hours"] == {"start": "00:00", "end": "23:59"}
    cy, _ = _user(app)
    follow(cy)
    _deliver(app)
    assert _pushes_to(app, push_token) == []

    # Quiet hours off: pushes flow, rendered in the reader's language.
    cleared = app.client.patch(
        "/v1/users/me/preferences", headers=_auth(bo), json={"quiet_hours": None}
    )
    assert cleared.json()["quiet_hours"] is None
    di, _ = _user(app)
    follow(di)
    _deliver(app)
    [pushed] = _pushes_to(app, push_token)
    assert pushed.data["type"] == "new_follower"
    assert pushed.title

    # A revoked session gets nothing more, and its token is deleted.
    sessions = app.client.get("/v1/users/me/sessions", headers=_auth(bo)).json()["data"]
    [current] = [s for s in sessions if s["is_current"]]
    revoke = app.client.delete(f"/v1/users/me/sessions/{current['id']}", headers=_auth(bo))
    assert revoke.status_code == 204
    assert (
        db_scalar(
            app.db_url,
            "SELECT count(*) FROM device_push_tokens WHERE user_id = :u",
            u=uuid.UUID(bo_id),
        )
        == 0
    )
    assert ana_id


@pytest.mark.req("NOTIF-002")
def test_tokens_the_provider_reports_gone_are_disabled(app: LiveApp) -> None:  # noqa: F811
    ana, _, bo, bo_id, conversation = _pair(app)
    push_token = _expo_token()
    assert _register(app, bo, push_token).status_code == 201
    _sender(app).gone.add(push_token)
    _sent(app, ana, conversation, "Hello")
    _deliver(app)
    disabled = db_scalar(
        app.db_url,
        "SELECT count(*) FROM device_push_tokens WHERE user_id = :u AND disabled_at IS NOT NULL",
        u=uuid.UUID(bo_id),
    )
    assert disabled == 1
    _sender(app).gone.clear()
    app.client.put(
        f"/v1/conversations/{conversation}/receipts",
        headers=_auth(bo),
        json={"read_through_seq": 1},
    )
    _sent(app, ana, conversation, "Again")
    _deliver(app)
    assert len(_pushes_to(app, push_token)) == 1  # the first attempt only; disabled since


@pytest.mark.req("NOTIF-005")
def test_browsers_receive_encrypted_web_push(catalog: str) -> None:  # noqa: F811
    from cryptography.hazmat.primitives.asymmetric import ec

    from tests.unit.test_webpush import browser_subscription, decrypt

    vapid = ec.generate_private_key(ec.SECP256R1())
    scalar = b64url(vapid.private_numbers().private_value.to_bytes(32, "big"))
    delivered: list[httpx.Request] = []

    def network(request: httpx.Request) -> httpx.Response:
        if request.url.host == "push.example":
            delivered.append(request)
            return httpx.Response(201)
        return httpx.Response(200, json={"data": []})  # Expo

    async def ok() -> bool:
        return True

    application = create_app(
        make_settings(
            database_url=catalog,
            dev_idp_enabled=True,
            cron_secret=SecretStr(CRON),
            push_provider="expo",
            web_push_vapid_private_key=SecretStr(scalar),
        ),
        identity_settings=make_identity_settings(),
        readiness_checks={"db": ok},
        clock=FixedClock(datetime.now(tz=UTC).replace(microsecond=0)),
        http_transport=httpx.MockTransport(network),
    )
    with TestClient(application, raise_server_exceptions=False) as client:
        live = LiveApp(client=client, clock=FixedClock(datetime.now(tz=UTC)), db_url=catalog)
        config = client.get("/v1/client-config", params={"platform": "web", "app_version": "1.0.0"})
        assert config.json()["web_push_vapid_public_key"] == b64url(_point(vapid.public_key()))

        ana, _ = _user(live)
        bo, bo_id = _user(live)
        receiver, p256dh, auth = browser_subscription()
        registered = client.post(
            "/v1/users/me/devices",
            headers=_auth(bo),
            json={
                "provider": "webpush",
                "device_id": "browser-0042",
                "subscription": {
                    "endpoint": "https://push.example/sub/bo",
                    "keys": {"p256dh": p256dh, "auth": auth},
                },
            },
        )
        assert registered.status_code == 201, registered.text
        assert client.put(f"/v1/users/{bo_id}/follow", headers=_auth(ana)).status_code in (200, 201)
        _deliver(live)
        [request] = delivered
        payload = json.loads(decrypt(request.content, receiver, auth))
        assert payload["data"]["type"] == "new_follower"
        assert request.headers["authorization"].startswith("vapid t=")
