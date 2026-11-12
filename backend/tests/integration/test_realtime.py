"""The realtime gateway end to end (BL-3.04; DM-003..008, docs/06)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from app.core.time import FixedClock
from app.main import create_app
from tests.conftest import make_identity_settings, make_settings
from tests.contract_schemas import assert_matches_contract, assert_realtime_frame
from tests.integration.conftest import LiveApp
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_messaging import _connect, _sent
from tests.integration.test_posts import CRON, _user

pytestmark = pytest.mark.integration

PROTOCOL = "travelbuddy.v1"
WEB = "https://web.example"


@pytest.fixture
def rt(catalog: str) -> Iterator[LiveApp]:  # noqa: F811
    async def ok() -> bool:
        return True

    clock = FixedClock(datetime.now(tz=UTC).replace(microsecond=0))
    application = create_app(
        make_settings(
            database_url=catalog,
            dev_idp_enabled=True,
            cron_secret=SecretStr(CRON),
            cors_allowed_origins=[WEB],
            realtime_auth_timeout_seconds=0.5,
        ),
        identity_settings=make_identity_settings(),
        readiness_checks={"db": ok},
        clock=clock,
    )
    with TestClient(application, raise_server_exceptions=False) as client:
        yield LiveApp(client=client, clock=clock, db_url=catalog)


def _frame(kind: str, data: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "v": 1,
        "type": kind,
        "id": str(uuid.uuid4()),
        "ts": datetime.now(tz=UTC).isoformat(),
        **extra,
    }
    if data is not None:
        out["data"] = data
    return out


class Reader:
    """Reads frames in order, keeping the ones a test skipped past for later expectations."""

    def __init__(self, ws: WebSocketTestSession) -> None:
        self.ws = ws
        self.pending: list[dict[str, Any]] = []

    def send(self, kind: str, data: dict[str, Any] | None = None, **extra: Any) -> str:
        frame = _frame(kind, data, **extra)
        self.ws.send_json(frame)
        return str(frame["id"])

    def expect(self, kind: str, **match: Any) -> dict[str, Any]:
        def matches(frame: dict[str, Any]) -> bool:
            return frame["type"] == kind and all(
                frame.get("data", {}).get(k) == v for k, v in match.items()
            )

        for index, frame in enumerate(self.pending):
            if matches(frame):
                return self.pending.pop(index)
        while True:
            frame = self.ws.receive_json()
            assert_realtime_frame(frame)
            if matches(frame):
                return frame
            self.pending.append(frame)

    def closed(self) -> int:
        """Read until the server closes; returns the close code."""
        while True:
            try:
                frame = self.ws.receive_json()
            except WebSocketDisconnect as closed:
                return int(closed.code)
            assert_realtime_frame(frame)
            self.pending.append(frame)

    def quiet(self) -> list[dict[str, Any]]:
        """Frames that arrived before a ping round trip (to assert nothing else was sent)."""
        self.send("ping", {})
        self.expect("pong")
        frames, self.pending = self.pending, []
        return frames


@contextmanager
def _socket(live: LiveApp, token: str) -> Iterator[Reader]:
    with live.client.websocket_connect("/v1/realtime", subprotocols=[PROTOCOL]) as ws:
        reader = Reader(ws)
        frame_id = reader.send("auth", {"access_token": token, "client": "android"})
        ok = reader.expect("auth.ok")
        assert ok["reply_to"] == frame_id
        assert ok["data"]["limits"]["message_send_per_minute"] == 30
        yield reader


def _pair(live: LiveApp) -> tuple[str, str, str, str, str]:
    ana, ana_id = _user(live)
    bo, bo_id = _user(live)
    _connect(live, ana_id, bo_id)
    opened = live.client.post(
        "/v1/conversations", headers=_auth(ana), json={"kind": "direct", "user_id": bo_id}
    )
    assert opened.status_code == 201, opened.text
    return ana, ana_id, bo, bo_id, str(opened.json()["id"])


# ─────────────────────────────── handshake ───────────────────────────────


@pytest.mark.req("DM-003")
def test_handshake_rejections(rt: LiveApp) -> None:
    token, _ = _user(rt)
    with rt.client.websocket_connect("/v1/realtime") as ws:  # no subprotocol
        assert Reader(ws).closed() == 4010

    with rt.client.websocket_connect(
        "/v1/realtime", subprotocols=[PROTOCOL], headers={"origin": "https://evil.example"}
    ) as ws:
        reader = Reader(ws)
        assert reader.closed() == 4005
        assert reader.pending[0]["data"]["code"] == "origin_not_allowed"

    with rt.client.websocket_connect("/v1/realtime", subprotocols=[PROTOCOL]) as ws:
        reader = Reader(ws)  # says nothing
        assert reader.closed() == 4002
        assert reader.pending[0]["data"]["code"] == "auth_timeout"

    with rt.client.websocket_connect("/v1/realtime", subprotocols=[PROTOCOL]) as ws:
        reader = Reader(ws)
        reader.send("ping", {})
        assert reader.closed() == 4001  # anything before auth

    with rt.client.websocket_connect("/v1/realtime", subprotocols=[PROTOCOL]) as ws:
        reader = Reader(ws)
        reader.send("auth", {"access_token": "x" * 40})
        assert reader.closed() == 4001
        assert reader.pending[0]["data"]["code"] == "token_invalid"

    with rt.client.websocket_connect("/v1/realtime", subprotocols=[PROTOCOL]) as ws:
        reader = Reader(ws)
        ws.send_json({**_frame("auth", {"access_token": token}), "v": 2})
        assert reader.closed() == 4010

    with rt.client.websocket_connect(
        "/v1/realtime", subprotocols=[PROTOCOL], headers={"origin": WEB}
    ) as ws:
        reader = Reader(ws)  # allow-listed browser origin
        reader.send("auth", {"access_token": token})
        reader.expect("auth.ok")


@pytest.mark.req("DM-003")
def test_reauth_keeps_the_same_session(rt: LiveApp) -> None:
    token, _ = _user(rt)
    other, _ = _user(rt)
    with _socket(rt, token) as reader:
        frame_id = reader.send("auth", {"access_token": token})
        assert reader.expect("auth.ok")["reply_to"] == frame_id
        reader.send("auth", {"access_token": other})
        assert reader.closed() == 4001
        assert reader.pending[-1]["data"]["code"] == "unauthenticated"


# ─────────────────────────────── delivery ───────────────────────────────


@pytest.mark.req("DM-003", "DM-004", "DM-005")
def test_socket_send_acks_after_persisting_and_fans_out(rt: LiveApp) -> None:
    ana, _, bo, bo_id, conversation = _pair(rt)
    with _socket(rt, ana) as ana_ws, _socket(rt, bo) as bo_ws:
        client_id = str(uuid.uuid4())
        payload = {"conversation_id": conversation, "client_message_id": client_id, "body": "Hey!"}
        frame_id = ana_ws.send("message.send", payload)
        ack = ana_ws.expect("message.ack")
        assert ack["reply_to"] == frame_id
        assert ack["data"]["seq"] == 1
        assert ack["data"]["duplicate"] is False
        mine = ana_ws.expect("message.new")["data"]["message"]
        assert mine["client_message_id"] == client_id  # the sender's own devices
        theirs = bo_ws.expect("message.new")["data"]["message"]
        assert theirs["id"] == ack["data"]["message_id"]
        assert theirs["body"] == "Hey!"
        assert theirs["client_message_id"] is None

        # A retry with the same client_message_id is acknowledged as a duplicate.
        ana_ws.send("message.send", payload)
        retry = ana_ws.expect("message.ack")
        assert retry["data"]["duplicate"] is True
        assert retry["data"]["message_id"] == ack["data"]["message_id"]

        # Sends over REST reach open sockets too.
        rest = _sent(rt, bo, conversation, "Over REST")
        assert ana_ws.expect("message.new")["data"]["message"]["id"] == rest["id"]
        assert bo_ws.expect("message.new")["data"]["message"]["id"] == rest["id"]

        # History has exactly the two messages, in seq order.
        history = rt.client.get(
            f"/v1/conversations/{conversation}/messages", headers=_auth(bo)
        ).json()
        assert [m["seq"] for m in history["data"]] == [1, 2]
        assert bo_id


@pytest.mark.req("DM-006", "DM-007", "DM-008", "DM-010")
def test_edits_deletes_reactions_receipts_and_typing(rt: LiveApp) -> None:
    ana, ana_id, bo, bo_id, conversation = _pair(rt)
    message = _sent(rt, ana, conversation, "Meet at 7")
    with _socket(rt, ana) as ana_ws, _socket(rt, bo) as bo_ws:
        ana_ws.send(
            "message.edit",
            {"conversation_id": conversation, "message_id": message["id"], "body": "Meet at 8"},
        )
        edited = bo_ws.expect("message.updated", change="edited")["data"]["message"]
        assert edited["body"] == "Meet at 8"
        assert edited["edited_at"] is not None

        react = f"/v1/conversations/{conversation}/messages/{message['id']}/reactions/%F0%9F%91%8D"
        assert rt.client.put(react, headers=_auth(bo)).status_code == 204
        reacted = ana_ws.expect("message.updated", change="reactions")["data"]["message"]
        assert reacted["reactions"] == [{"emoji": "👍", "count": 1, "reacted_by_me": False}]
        assert bo_ws.expect("message.updated", change="reactions")["data"]["message"][
            "reactions"
        ] == [{"emoji": "👍", "count": 1, "reacted_by_me": True}]

        bo_ws.send(
            "receipt.delivered", {"conversation_id": conversation, "delivered_through_seq": 1}
        )
        delivered = ana_ws.expect("receipt.updated")["data"]
        assert delivered == {
            "conversation_id": conversation,
            "user_id": bo_id,
            "delivered_through_seq": 1,
        }
        bo_ws.send("receipt.read", {"conversation_id": conversation, "read_through_seq": 1})
        read = ana_ws.expect("receipt.updated")["data"]
        assert read["read_through_seq"] == 1
        assert bo_ws.quiet() == []  # the reader isn't told about their own receipts

        bo_ws.send("typing.start", {"conversation_id": conversation})
        typing = ana_ws.expect("typing")["data"]
        assert (typing["user_id"], typing["state"]) == (bo_id, "started")
        bo_ws.send("typing.start", {"conversation_id": conversation})  # within 3 s: dropped
        bo_ws.send("typing.stop", {"conversation_id": conversation})
        assert ana_ws.expect("typing")["data"]["state"] == "stopped"

        ana_ws.send(
            "message.delete", {"conversation_id": conversation, "message_id": message["id"]}
        )
        deleted = bo_ws.expect("message.deleted")["data"]
        assert deleted["message_id"] == message["id"]
        assert deleted["by_moderator"] is False
        assert ana_id


@pytest.mark.req("DM-007")
def test_read_receipts_need_both_sides_to_share(rt: LiveApp) -> None:
    ana, _, bo, _, conversation = _pair(rt)
    _sent(rt, ana, conversation, "One")
    privacy = rt.client.patch(
        "/v1/users/me/privacy", headers=_auth(bo), json={"read_receipts_enabled": False}
    )
    assert privacy.status_code == 200
    with _socket(rt, ana) as ana_ws, _socket(rt, bo) as bo_ws:
        bo_ws.send("receipt.read", {"conversation_id": conversation, "read_through_seq": 1})
        bo_ws.quiet()
        update = ana_ws.expect("receipt.updated")["data"]  # delivery is implied by the read
        assert "read_through_seq" not in update
        assert update["delivered_through_seq"] == 1


# ─────────────────────────────── errors and sync ───────────────────────────────


@pytest.mark.req("DM-006")
def test_errors_sync_and_heartbeat(rt: LiveApp) -> None:
    ana, _, _, _, conversation = _pair(rt)
    for text in ("a", "b", "c"):
        _sent(rt, ana, conversation, text)
    stranger, _ = _user(rt)
    with _socket(rt, stranger) as ws:
        frame_id = ws.send(
            "message.send",
            {"conversation_id": conversation, "client_message_id": str(uuid.uuid4()), "body": "x"},
        )
        error = ws.expect("error")
        assert error["reply_to"] == frame_id
        assert error["data"]["code"] == "not_found"  # same as a conversation that doesn't exist

    with _socket(rt, ana) as ws:
        ws.send("presence.query", {})
        assert ws.expect("error")["data"]["code"] == "unknown_type"
        ws.send("message.send", {"conversation_id": conversation, "body": "no client id"})
        assert ws.expect("error")["data"]["code"] == "validation_failed"
        ws.send("ping", {})
        ws.expect("pong")

        ws.send(
            "sync.request", {"conversations": [{"conversation_id": conversation, "last_seq": 1}]}
        )
        sync = ws.expect("sync.required")["data"]
        assert sync["reason"] == "reconnect"
        assert sync["conversations"] == [
            {"conversation_id": conversation, "from_seq": 1, "server_last_seq": 3}
        ]
        ws.send(
            "sync.request", {"conversations": [{"conversation_id": conversation, "last_seq": 3}]}
        )
        assert ws.expect("sync.required")["data"]["conversations"] == []
        ws.send(
            "sync.request",
            {"conversations": [], "conversation_list_synced_at": "2000-01-01T00:00:00Z"},
        )
        assert [
            c["conversation_id"] for c in ws.expect("sync.required")["data"]["conversations"]
        ] == [conversation]

        for _ in range(3):  # the invalid send above was the first of five
            ws.send("receipt.read", {"conversation_id": "not-a-uuid", "read_through_seq": 1})
            ws.expect("error")
        ws.send("receipt.read", {"conversation_id": "not-a-uuid", "read_through_seq": 1})
        assert ws.closed() == 4000  # repeated invalid frames


@pytest.mark.req("DM-012", "SAFE-001")
def test_block_stops_typing_and_sending_over_the_socket(rt: LiveApp) -> None:
    ana, _, bo, bo_id, conversation = _pair(rt)
    with _socket(rt, ana) as ana_ws, _socket(rt, bo) as bo_ws:
        assert rt.client.put(f"/v1/users/{bo_id}/block", headers=_auth(ana)).status_code == 204
        bo_ws.send("typing.start", {"conversation_id": conversation})
        bo_ws.quiet()
        assert ana_ws.quiet() == []  # no typing across a block
        bo_ws.send(
            "message.send",
            {"conversation_id": conversation, "client_message_id": str(uuid.uuid4()), "body": "x"},
        )
        assert bo_ws.expect("error")["data"]["code"] == "connection_required"


@pytest.mark.req("DM-003", "AUTH-011")
def test_browsers_authenticate_with_single_use_tickets(rt: LiveApp) -> None:
    token, user_id = _user(rt)

    def mint() -> str:
        response = rt.client.post("/v1/realtime/tickets", headers=_auth(token))
        assert response.status_code == 201, response.text
        assert response.headers["cache-control"] == "no-store"
        assert_matches_contract(response.json(), "RealtimeTicket")
        ticket: str = response.json()["ticket"]
        return ticket

    ticket = mint()
    with rt.client.websocket_connect(
        "/v1/realtime", subprotocols=[PROTOCOL], headers={"origin": WEB}
    ) as ws:
        reader = Reader(ws)
        reader.send("auth", {"ticket": ticket, "client": "web"})
        ok = reader.expect("auth.ok")["data"]
        assert ok["user_id"] == user_id
        issued = datetime.fromisoformat(ok["server_time"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(ok["auth_expires_at"].replace("Z", "+00:00"))
        assert timedelta(minutes=14) < expires - issued <= timedelta(minutes=15)
        reader.send("auth", {"ticket": mint(), "client": "web"})  # re-auth, same session
        reader.expect("auth.ok")

    with rt.client.websocket_connect("/v1/realtime", subprotocols=[PROTOCOL]) as ws:
        reader = Reader(ws)
        reader.send("auth", {"ticket": ticket})  # single use
        assert reader.closed() == 4001
        assert reader.pending[0]["data"]["code"] == "ticket_invalid"

    # Revoking the session voids its outstanding tickets.
    pending = mint()
    sessions = rt.client.get("/v1/users/me/sessions", headers=_auth(token)).json()["data"]
    [current] = [s for s in sessions if s["is_current"]]
    assert (
        rt.client.delete(f"/v1/users/me/sessions/{current['id']}", headers=_auth(token)).status_code
        == 204
    )
    with rt.client.websocket_connect("/v1/realtime", subprotocols=[PROTOCOL]) as ws:
        reader = Reader(ws)
        reader.send("auth", {"ticket": pending})
        assert reader.closed() == 4001


# ─────────────────────────────── notifications ───────────────────────────────


@pytest.mark.req("NOTIF-001", "CONN-001")
def test_a_connection_request_reaches_the_open_app_at_once(rt: LiveApp) -> None:
    """ADR-0033: the job that creates the notification announces it on the recipient's socket."""
    from tests.integration.test_connections import _send
    from tests.integration.test_posts import _tick

    ana, ana_id = _user(rt)
    bo, bo_id = _user(rt)
    with _socket(rt, ana) as ana_ws, _socket(rt, bo) as bo_ws:
        sent = _send(rt, bo, ana_id)
        assert sent.status_code == 201, sent.text
        _tick(rt)
        frame = ana_ws.expect("notification.new")
        assert_realtime_frame(frame)
        notification = frame["data"]["notification"]
        assert notification["type"] == "connection_request"
        assert notification["actor"]["id"] == bo_id
        assert notification["title"]
        assert "read_at" not in notification
        assert all(f["type"] != "notification.new" for f in bo_ws.quiet())
