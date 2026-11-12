"""Direct conversations and messages end to end (BL-3.03; DM-001..016, SAFE-001/002)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.modules.notifications.domain import GIFT_TEXTS, MODERATION_BODIES
from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_moderation import _admin, _staff
from tests.integration.test_posts import _problem, _tick, _user, app  # noqa: F401

pytestmark = pytest.mark.integration


def _connect(live: LiveApp, a: str, b: str) -> None:
    low, high = sorted((a, b))
    db_scalar(
        live.db_url,
        "INSERT INTO user_connections (user_low_id, user_high_id) VALUES (:l, :h) RETURNING 1",
        l=uuid.UUID(low),
        h=uuid.UUID(high),
    )


def _pair(live: LiveApp) -> tuple[str, str, str, str, str]:
    """Two connected travellers and their direct conversation: (ana, ana_id, bo, bo_id, conv)."""
    ana, ana_id = _user(live)
    bo, bo_id = _user(live)
    _connect(live, ana_id, bo_id)
    opened = _open(live, ana, bo_id)
    assert opened.status_code == 201, opened.text
    return ana, ana_id, bo, bo_id, str(opened.json()["id"])


def _open(live: LiveApp, token: str, user_id: str) -> Any:
    return live.client.post(
        "/v1/conversations", headers=_auth(token), json={"kind": "direct", "user_id": user_id}
    )


def _send(live: LiveApp, token: str, conversation: str, body: str = "Hi!", **extra: Any) -> Any:
    payload = {"client_message_id": str(uuid.uuid4()), "body": body, **extra}
    if payload.get("body") is None:
        payload.pop("body")
    return live.client.post(
        f"/v1/conversations/{conversation}/messages",
        headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())},
        json=payload,
    )


def _sent(live: LiveApp, token: str, conversation: str, body: str = "Hi!") -> dict[str, Any]:
    response = _send(live, token, conversation, body)
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    return data


def _messages(live: LiveApp, token: str, conversation: str, **params: Any) -> dict[str, Any]:
    response = live.client.get(
        f"/v1/conversations/{conversation}/messages", headers=_auth(token), params=params
    )
    assert response.status_code == 200, response.text
    assert_matches_contract(response.json(), "MessageList")
    data: dict[str, Any] = response.json()
    return data


def _conversation(live: LiveApp, token: str, conversation: str) -> dict[str, Any]:
    response = live.client.get(f"/v1/conversations/{conversation}", headers=_auth(token))
    assert response.status_code == 200, response.text
    assert_matches_contract(response.json(), "Conversation")
    data: dict[str, Any] = response.json()
    return data


def _receipts(live: LiveApp, token: str, conversation: str, **body: int) -> dict[str, Any]:
    response = live.client.put(
        f"/v1/conversations/{conversation}/receipts", headers=_auth(token), json=body
    )
    assert response.status_code == 200, response.text
    assert_matches_contract(response.json(), "ReceiptState")
    data: dict[str, Any] = response.json()
    return data


def _notifications(live: LiveApp, token: str) -> list[dict[str, Any]]:
    response = live.client.get("/v1/notifications", headers=_auth(token))
    assert response.status_code == 200, response.text
    data: list[dict[str, Any]] = response.json()["data"]
    return data


# ─────────────────────────────── conversations ───────────────────────────────


@pytest.mark.req("DM-001")
def test_direct_conversation_needs_a_connection_and_is_unique_per_pair(app: LiveApp) -> None:  # noqa: F811
    ana, ana_id = _user(app)
    bo, bo_id = _user(app)
    _problem(_open(app, ana, bo_id), 403, "connection_required")
    _problem(_open(app, ana, ana_id), 422, "validation_failed")
    _problem(_open(app, ana, str(uuid.uuid4())), 404, "not_found")

    _connect(app, ana_id, bo_id)
    created = _open(app, ana, bo_id)
    assert created.status_code == 201, created.text
    assert_matches_contract(created.json(), "Conversation")
    conversation = created.json()
    assert conversation["kind"] == "direct"
    assert conversation["counterpart"]["id"] == bo_id
    assert conversation["can_send"] is True
    assert conversation["send_restriction"] is None
    assert conversation["last_seq"] == 0
    assert conversation["last_message"] is None
    again = _open(app, ana, bo_id)
    assert again.status_code == 200
    assert again.json()["id"] == conversation["id"]
    theirs = _open(app, bo, ana_id)
    assert theirs.status_code == 200
    assert theirs.json()["id"] == conversation["id"]
    assert theirs.json()["counterpart"]["id"] == ana_id

    # Members only; an empty conversation stays out of the list until someone writes.
    outsider, _ = _user(app)
    _problem(
        app.client.get(f"/v1/conversations/{conversation['id']}", headers=_auth(outsider)),
        404,
        "not_found",
    )
    listed = app.client.get("/v1/conversations", headers=_auth(bo)).json()
    assert listed["data"] == []
    _sent(app, ana, conversation["id"])
    listed = app.client.get("/v1/conversations", headers=_auth(bo))
    assert_matches_contract(listed.json(), "ConversationPage")
    [item] = listed.json()["data"]
    assert item["id"] == conversation["id"]
    assert item["unread_count"] == 1
    assert item["last_message"]["snippet"] == "Hi!"


@pytest.mark.req("DM-001")
def test_conversation_list_orders_by_activity_and_paginates(app: LiveApp) -> None:  # noqa: F811
    ana, ana_id = _user(app)
    conversations = []
    for _ in range(3):
        _, other_id = _user(app)
        _connect(app, ana_id, other_id)
        conversations.append(_open(app, ana, other_id).json()["id"])
    for conversation in conversations:
        _sent(app, ana, conversation)
    _sent(app, ana, conversations[0], "Back to you")  # most recent activity
    first = app.client.get("/v1/conversations", headers=_auth(ana), params={"limit": 2}).json()
    assert [c["id"] for c in first["data"]] == [conversations[0], conversations[2]]
    assert first["page"]["has_more"] is True
    second = app.client.get(
        "/v1/conversations",
        headers=_auth(ana),
        params={"limit": 2, "cursor": first["page"]["next_cursor"]},
    ).json()
    assert [c["id"] for c in second["data"]] == [conversations[1]]
    assert second["page"]["has_more"] is False


# ─────────────────────────────── sending ───────────────────────────────


@pytest.mark.req("DM-004", "DM-005", "DM-006")
def test_send_is_idempotent_ordered_and_syncs_by_seq(app: LiveApp) -> None:  # noqa: F811
    ana, _, bo, _, conversation = _pair(app)
    client_id = str(uuid.uuid4())
    payload = {"client_message_id": client_id, "body": "First!"}
    headers = {**_auth(ana), "Idempotency-Key": str(uuid.uuid4())}
    url = f"/v1/conversations/{conversation}/messages"
    first = app.client.post(url, headers=headers, json=payload)
    assert first.status_code == 201, first.text
    assert_matches_contract(first.json(), "Message")
    assert first.json()["seq"] == 1
    assert first.json()["client_message_id"] == client_id
    retry = app.client.post(
        url, headers={**_auth(ana), "Idempotency-Key": str(uuid.uuid4())}, json=payload
    )
    assert retry.status_code == 200
    assert retry.headers.get("Idempotent-Replayed") == "true"
    assert (retry.json()["id"], retry.json()["seq"]) == (first.json()["id"], 1)
    assert app.client.post(url, headers=_auth(ana), json=payload).status_code == 422  # key needed

    assert _sent(app, bo, conversation, "Second")["seq"] == 2
    assert _sent(app, ana, conversation, "Third")["seq"] == 3
    everything = _messages(app, bo, conversation)
    assert [m["seq"] for m in everything["data"]] == [1, 2, 3]
    assert [m["body"] for m in everything["data"]] == ["First!", "Second", "Third"]
    assert everything["data"][0]["client_message_id"] is None  # only the sender sees it
    assert everything["data"][1]["client_message_id"] is not None
    assert everything["page"] == {"has_more": False, "oldest_seq": 1, "newest_seq": 3}

    gap = _messages(app, bo, conversation, after_seq=1)
    assert [m["seq"] for m in gap["data"]] == [2, 3]
    older = _messages(app, bo, conversation, before_seq=3, limit=1)
    assert [m["seq"] for m in older["data"]] == [2]
    assert older["page"]["has_more"] is True
    latest = _messages(app, bo, conversation, limit=2)
    assert [m["seq"] for m in latest["data"]] == [2, 3]
    _problem(
        app.client.get(
            f"/v1/conversations/{conversation}/messages",
            headers=_auth(bo),
            params={"after_seq": 1, "before_seq": 3},
        ),
        422,
        "validation_failed",
    )


@pytest.mark.req("DM-002")
@pytest.mark.parametrize(
    ("extra", "field"),
    [
        ({"body": "   "}, None),
        ({"body": None}, None),
        ({"body": "x" * 4001}, None),
        ({"kind": "image"}, None),
        ({"thread_root_id": str(uuid.uuid4())}, "/thread_root_id"),
        ({"reply_to_message_id": str(uuid.uuid4())}, "/reply_to_message_id"),
        ({"attachment_media_ids": [str(uuid.uuid4())]}, "/attachment_media_ids"),
    ],
)
def test_invalid_messages_are_rejected(
    app: LiveApp,  # noqa: F811
    extra: dict[str, Any],
    field: str | None,
) -> None:
    ana, _, _, _, conversation = _pair(app)
    problem = _problem(_send(app, ana, conversation, **extra), 422, "validation_failed")
    if field:
        assert [e["field"] for e in problem["errors"]] == [field]


@pytest.mark.req("DM-002")
def test_image_messages_attach_own_message_media(app: LiveApp) -> None:  # noqa: F811
    ana, ana_id, bo, bo_id, conversation = _pair(app)

    def asset(owner: str, purpose: str = "message") -> str:
        return str(
            db_scalar(
                app.db_url,
                "INSERT INTO media_assets (id, owner_id, purpose, status, mime_type, bytes, "
                "sha256, quarantine_key) VALUES (gen_random_uuid(), :o, :p, 'scanning', "
                "'image/jpeg', 10, 'x', 'q') RETURNING id",
                o=uuid.UUID(owner),
                p=purpose,
            )
        )

    mine = asset(ana_id)
    sent = _send(app, ana, conversation, None, kind="image", attachment_media_ids=[mine])
    assert sent.status_code == 201, sent.text
    assert [a["id"] for a in sent.json()["attachments"]] == [mine]
    for other in (asset(bo_id), asset(ana_id, "post")):
        _problem(
            _send(app, ana, conversation, None, kind="image", attachment_media_ids=[other]),
            422,
            "validation_failed",
        )

    # Deleting the message erases its attachment.
    assert (
        app.client.delete(
            f"/v1/conversations/{conversation}/messages/{sent.json()['id']}", headers=_auth(ana)
        ).status_code
        == 204
    )
    assert (
        db_scalar(
            app.db_url,
            "SELECT count(*) FROM media_assets WHERE id = :m",
            m=uuid.UUID(mine),
        )
        == 0
    )
    assert _messages(app, bo, conversation)["data"][0]["attachments"] == []


@pytest.mark.req("DM-002")
def test_replies_mentions_and_threads(app: LiveApp) -> None:  # noqa: F811
    ana, ana_id, bo, _bo_id, conversation = _pair(app)
    first = _sent(app, ana, conversation, "Dinner at 8?")
    reply = _send(
        app,
        bo,
        conversation,
        "Sounds great",
        reply_to_message_id=first["id"],
        mentions=[ana_id, str(uuid.uuid4())],  # non-members are dropped
    )
    assert reply.status_code == 201, reply.text
    assert reply.json()["reply_to"]["id"] == first["id"]
    assert reply.json()["reply_to"]["snippet"] == "Dinner at 8?"
    assert reply.json()["mentions"] == [ana_id]
    _problem(
        _send(app, bo, conversation, "x", thread_root_id=first["id"]), 422, "validation_failed"
    )  # threads are for group chats
    thread = app.client.get(
        f"/v1/conversations/{conversation}/threads/{first['id']}", headers=_auth(bo)
    )
    assert thread.status_code == 200
    assert thread.json()["data"] == []


# ─────────────────────────────── edit and delete ───────────────────────────────


@pytest.mark.req("DM-010")
def test_edit_within_window_and_delete_leaves_a_tombstone(app: LiveApp) -> None:  # noqa: F811
    ana, _, bo, _, conversation = _pair(app)
    message = _sent(app, ana, conversation, "See you at 7")
    url = f"/v1/conversations/{conversation}/messages/{message['id']}"
    edited = app.client.patch(url, headers=_auth(ana), json={"body": "See you at 8"})
    assert edited.status_code == 200, edited.text
    assert_matches_contract(edited.json(), "Message")
    assert edited.json()["body"] == "See you at 8"
    assert edited.json()["edited_at"] is not None
    assert edited.json()["seq"] == message["seq"]
    _problem(app.client.patch(url, headers=_auth(bo), json={"body": "Nope"}), 403, "forbidden")

    db_scalar(
        app.db_url,
        "UPDATE messages SET created_at = now() - interval '16 minutes' WHERE id = :m RETURNING 1",
        m=uuid.UUID(message["id"]),
    )
    _problem(
        app.client.patch(url, headers=_auth(ana), json={"body": "Late"}),
        403,
        "message_edit_window_expired",
    )

    _problem(app.client.delete(url, headers=_auth(bo)), 403, "forbidden")
    assert app.client.delete(url, headers=_auth(ana)).status_code == 204
    assert app.client.delete(url, headers=_auth(ana)).status_code == 204  # idempotent
    [tombstone] = _messages(app, bo, conversation)["data"]
    assert tombstone["body"] is None
    assert tombstone["deleted_at"] is not None
    assert tombstone["seq"] == message["seq"]
    preview = _conversation(app, bo, conversation)["last_message"]
    assert preview["deleted"] is True
    assert preview["snippet"] is None
    _problem(app.client.patch(url, headers=_auth(ana), json={"body": "x"}), 404, "not_found")


# ─────────────────────────────── receipts ───────────────────────────────


@pytest.mark.req("DM-006", "DM-007")
def test_receipts_are_monotonic_and_reciprocal(app: LiveApp) -> None:  # noqa: F811
    ana, _, bo, _, conversation = _pair(app)
    for text in ("one", "two", "three"):
        _sent(app, ana, conversation, text)
    assert _conversation(app, bo, conversation)["unread_count"] == 3
    state = _receipts(app, bo, conversation, delivered_through_seq=3, read_through_seq=1)
    assert (state["read_through_seq"], state["delivered_through_seq"]) == (1, 3)
    assert _conversation(app, bo, conversation)["unread_count"] == 2
    lower = _receipts(app, bo, conversation, read_through_seq=0)  # never moves back
    assert lower["read_through_seq"] == 1
    clamped = _receipts(app, bo, conversation, read_through_seq=99)  # never beyond last_seq
    assert clamped["read_through_seq"] == 3
    assert _conversation(app, bo, conversation)["unread_count"] == 0

    seen = _conversation(app, ana, conversation)
    assert seen["peer_read_through_seq"] == 3
    assert seen["peer_delivered_through_seq"] == 3
    assert seen["read_through_seq"] == 3  # sending marks your own messages read
    assert seen["unread_count"] == 0

    # Turning read receipts off hides read state both ways; delivery stays visible.
    privacy = app.client.patch(
        "/v1/users/me/privacy", headers=_auth(bo), json={"read_receipts_enabled": False}
    )
    assert privacy.status_code == 200, privacy.text
    assert _conversation(app, ana, conversation)["peer_read_through_seq"] is None
    assert _conversation(app, ana, conversation)["peer_delivered_through_seq"] == 3
    assert _conversation(app, bo, conversation)["peer_read_through_seq"] is None
    _problem(
        app.client.put(f"/v1/conversations/{conversation}/receipts", headers=_auth(bo), json={}),
        422,
        "validation_failed",
    )


# ─────────────────────────────── mute, clear, notifications ───────────────────────────────


@pytest.mark.req("DM-008", "DM-009", "DM-011")
def test_new_message_notifications_collapse_and_respect_mute(app: LiveApp) -> None:  # noqa: F811
    ana, ana_id, bo, _, conversation = _pair(app)
    _sent(app, ana, conversation, "One")
    _sent(app, ana, conversation, "Two")
    _tick(app)
    [notice] = [n for n in _notifications(app, bo) if n["type"] == "new_message"]
    assert notice["actor"]["id"] == ana_id
    assert "One" not in str(notice)
    assert "Two" not in str(notice)
    assert notice["read_at"] is None

    _receipts(app, bo, conversation, read_through_seq=2)
    _tick(app)
    [notice] = [n for n in _notifications(app, bo) if n["type"] == "new_message"]
    assert notice["read_at"] is not None
    _sent(app, ana, conversation, "Three")
    _tick(app)
    assert len([n for n in _notifications(app, bo) if n["type"] == "new_message"]) == 2

    muted = app.client.put(
        f"/v1/conversations/{conversation}/mute",
        headers=_auth(bo),
        json={"muted_until": "2099-01-01T00:00:00Z", "notification_level": "mentions"},
    )
    assert muted.status_code == 200, muted.text
    assert_matches_contract(muted.json(), "Conversation")
    assert muted.json()["notification_level"] == "mentions"
    assert muted.json()["muted_until"].startswith("2099-01-01")
    _receipts(app, bo, conversation, read_through_seq=3)
    _sent(app, ana, conversation, "Four")
    _tick(app)
    assert len([n for n in _notifications(app, bo) if n["type"] == "new_message"]) == 2


# ─────────────────────────────────── gifts ───────────────────────────────────


def _gift(
    live: LiveApp, token: str, conversation: str, gift: str = "coffee", effect: str | None = None
) -> Any:
    return live.client.post(
        f"/v1/conversations/{conversation}/messages",
        headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "client_message_id": str(uuid.uuid4()),
            "kind": "gift",
            "gift": gift,
            **({"gift_effect": effect} if effect else {}),
        },
    )


def _open_gift(live: LiveApp, token: str, conversation: str, message_id: str) -> Any:
    return live.client.post(
        f"/v1/conversations/{conversation}/messages/{message_id}/gift/open", headers=_auth(token)
    )


@pytest.mark.req("DM-016")
def test_gifts_are_sent_wrapped_and_opened_once_by_the_recipient(app: LiveApp) -> None:  # noqa: F811
    ana, _, bo, _, conversation = _pair(app)
    sent = _gift(app, ana, conversation, "snow_globe")
    assert sent.status_code == 201, sent.text
    assert_matches_contract(sent.json(), "Message")
    gift = sent.json()
    assert gift["kind"] == "gift"
    assert gift["body"] is None
    assert gift["gift"] == {"code": "snow_globe", "effect": "petals", "opened_at": None}
    [seen] = _messages(app, bo, conversation)["data"]
    assert seen["gift"] == {"code": "snow_globe", "effect": "petals", "opened_at": None}
    last = _conversation(app, bo, conversation)["last_message"]
    assert last["kind"] == "gift"
    assert last["snippet"] is None
    assert last["deleted"] is False

    # Only the recipient unwraps it; the sender can't, and neither can anyone outside the chat.
    _problem(_open_gift(app, ana, conversation, gift["id"]), 403, "forbidden")
    stranger, _ = _user(app)
    _problem(_open_gift(app, stranger, conversation, gift["id"]), 404, "not_found")
    opened = _open_gift(app, bo, conversation, gift["id"])
    assert opened.status_code == 200, opened.text
    assert_matches_contract(opened.json(), "Message")
    opened_at = opened.json()["gift"]["opened_at"]
    assert opened_at is not None
    again = _open_gift(app, bo, conversation, gift["id"])
    assert again.status_code == 200, again.text
    assert again.json()["gift"]["opened_at"] == opened_at  # idempotent
    [mine] = _messages(app, ana, conversation)["data"]
    assert mine["gift"]["opened_at"] == opened_at

    # A text message isn't a gift; a gift can't be edited, but it can be unsent.
    text = _sent(app, bo, conversation, "Thank you!")
    _problem(_open_gift(app, ana, conversation, text["id"]), 403, "forbidden")
    edit = app.client.patch(
        f"/v1/conversations/{conversation}/messages/{gift['id']}",
        headers=_auth(ana),
        json={"body": "A coffee"},
    )
    _problem(edit, 403, "forbidden")
    second = _gift(app, ana, conversation, "cake")
    assert second.status_code == 201, second.text
    deleted = app.client.delete(
        f"/v1/conversations/{conversation}/messages/{second.json()['id']}", headers=_auth(ana)
    )
    assert deleted.status_code == 204, deleted.text
    tombstone = _messages(app, bo, conversation)["data"][-1]
    assert tombstone["gift"] is None
    assert tombstone["deleted_at"] is not None
    _problem(_open_gift(app, bo, conversation, second.json()["id"]), 404, "not_found")


@pytest.mark.req("DM-016")
@pytest.mark.parametrize(
    "extra",
    [
        {"gift": "diamond_ring"},  # not in the catalog
        {"gift": None},
        {"gift": "coffee", "body": "and a note"},
        {"gift": "coffee", "attachment_media_ids": [str(uuid.uuid4())]},
        {"gift": "coffee", "gift_effect": "fireworks"},  # not an effect the apps draw
        {"gift_effect": "petals"},  # an effect without a gift
    ],
)
def test_invalid_gifts_are_rejected(app: LiveApp, extra: dict[str, Any]) -> None:  # noqa: F811
    ana, _, _, _, conversation = _pair(app)
    payload = {"client_message_id": str(uuid.uuid4()), "kind": "gift", **extra}
    response = app.client.post(
        f"/v1/conversations/{conversation}/messages",
        headers={**_auth(ana), "Idempotency-Key": str(uuid.uuid4())},
        json={k: v for k, v in payload.items() if v is not None},
    )
    _problem(response, 422, "validation_failed")
    # A gift name on a text message is refused too.
    _problem(_send(app, ana, conversation, "Hi", gift="coffee"), 422, "validation_failed")
    _problem(_send(app, ana, conversation, "Hi", gift_effect="hearts"), 422, "validation_failed")


@pytest.mark.req("DM-016")
@pytest.mark.parametrize("effect", ["petals", "splash", "confetti", "hearts"])
def test_the_sender_chooses_how_a_gift_opens(app: LiveApp, effect: str) -> None:  # noqa: F811
    ana, _, bo, _, conversation = _pair(app)
    sent = _gift(app, ana, conversation, "flowers", effect)
    assert sent.status_code == 201, sent.text
    assert_matches_contract(sent.json(), "Message")
    assert sent.json()["gift"]["effect"] == effect
    [seen] = _messages(app, bo, conversation)["data"]
    assert seen["gift"] == {"code": "flowers", "effect": effect, "opened_at": None}
    opened = _open_gift(app, bo, conversation, seen["id"])
    assert opened.status_code == 200, opened.text
    assert opened.json()["gift"]["effect"] == effect  # opening keeps the sender's choice


@pytest.mark.req("DM-016")
def test_a_gift_notifies_as_a_gift(app: LiveApp) -> None:  # noqa: F811
    ana, ana_id, bo, _, conversation = _pair(app)
    assert _gift(app, ana, conversation, "flowers").status_code == 201
    _tick(app)
    [notice] = [n for n in _notifications(app, bo) if n["type"] == "new_message"]
    assert notice["actor"]["id"] == ana_id
    name = notice["actor"]["display_name"]
    titles, bodies = GIFT_TEXTS  # rendered in the reader's language
    assert (notice["title"], notice["body"]) in {
        (titles[locale], bodies[locale].format(actor=name)) for locale in titles
    }


@pytest.mark.req("DM-011")
def test_clear_hides_history_for_me_only(app: LiveApp) -> None:  # noqa: F811
    ana, _, bo, _, conversation = _pair(app)
    for text in ("a", "b", "c"):
        _sent(app, ana, conversation, text)
    cleared = app.client.post(
        f"/v1/conversations/{conversation}/clear", headers=_auth(bo), json={"through_seq": 2}
    )
    assert cleared.status_code == 204
    assert [m["seq"] for m in _messages(app, bo, conversation)["data"]] == [3]
    assert [m["seq"] for m in _messages(app, ana, conversation)["data"]] == [1, 2, 3]
    assert _conversation(app, bo, conversation)["unread_count"] == 1
    _sent(app, ana, conversation, "d")
    assert [m["body"] for m in _messages(app, bo, conversation)["data"]] == ["c", "d"]


# ─────────────────────────────── reactions and pins ───────────────────────────────


@pytest.mark.req("DM-002")
def test_reactions_and_pins(app: LiveApp) -> None:  # noqa: F811
    ana, _, bo, _, conversation = _pair(app)
    message = _sent(app, ana, conversation, "Sunset spot: Miradouro")
    react = f"/v1/conversations/{conversation}/messages/{message['id']}/reactions"
    assert app.client.put(f"{react}/%F0%9F%91%8D", headers=_auth(bo)).status_code == 204
    assert app.client.put(f"{react}/%F0%9F%91%8D", headers=_auth(bo)).status_code == 204
    assert app.client.put(f"{react}/%E2%9D%A4", headers=_auth(ana)).status_code == 204  # ❤ → ❤️
    _problem(app.client.put(f"{react}/hello", headers=_auth(bo)), 422, "validation_failed")
    [shown] = _messages(app, bo, conversation)["data"]
    assert shown["reactions"] == [
        {"emoji": "👍", "count": 1, "reacted_by_me": True},
        {"emoji": "❤️", "count": 1, "reacted_by_me": False},
    ]
    assert app.client.delete(f"{react}/%F0%9F%91%8D", headers=_auth(bo)).status_code == 204
    assert app.client.delete(f"{react}/%F0%9F%91%8D", headers=_auth(bo)).status_code == 204
    assert [r["emoji"] for r in _messages(app, bo, conversation)["data"][0]["reactions"]] == ["❤️"]

    pins = f"/v1/conversations/{conversation}/pins"
    assert app.client.put(f"{pins}/{message['id']}", headers=_auth(bo)).status_code == 204
    assert app.client.put(f"{pins}/{message['id']}", headers=_auth(bo)).status_code == 204
    listed = app.client.get(pins, headers=_auth(ana))
    assert listed.status_code == 200
    assert_matches_contract(listed.json(), "MessageList")
    assert [m["id"] for m in listed.json()["data"]] == [message["id"]]
    assert listed.json()["data"][0]["pinned"] is True
    for index in range(9):
        extra = _sent(app, ana, conversation, f"pin {index}")
        assert app.client.put(f"{pins}/{extra['id']}", headers=_auth(ana)).status_code == 204
    eleventh = _sent(app, ana, conversation, "one too many")
    _problem(app.client.put(f"{pins}/{eleventh['id']}", headers=_auth(ana)), 409, "conflict")
    assert app.client.delete(f"{pins}/{message['id']}", headers=_auth(ana)).status_code == 204
    assert app.client.put(f"{pins}/{eleventh['id']}", headers=_auth(ana)).status_code == 204


# ─────────────────────────────── safety ───────────────────────────────


@pytest.mark.req("DM-012", "SAFE-001")
def test_block_stops_delivery_both_ways(app: LiveApp) -> None:  # noqa: F811
    ana, ana_id, bo, bo_id, conversation = _pair(app)
    _sent(app, ana, conversation, "Before the block")
    blocked = app.client.put(f"/v1/users/{bo_id}/block", headers=_auth(ana))
    assert blocked.status_code == 204, blocked.text

    _problem(_send(app, ana, conversation, "x"), 403, "blocked_relationship")
    _problem(_send(app, bo, conversation, "x"), 403, "connection_required")
    mine = _conversation(app, ana, conversation)
    assert (mine["can_send"], mine["send_restriction"]) == (False, "blocked")
    theirs = _conversation(app, bo, conversation)  # the block itself is not revealed
    assert (theirs["can_send"], theirs["send_restriction"]) == (False, "connection_required")
    assert [m["body"] for m in _messages(app, bo, conversation)["data"]] == ["Before the block"]
    _problem(_open(app, bo, ana_id), 404, "not_found")
    [message] = _messages(app, ana, conversation)["data"]
    react = f"/v1/conversations/{conversation}/messages/{message['id']}/reactions/%F0%9F%91%8D"
    _problem(app.client.put(react, headers=_auth(bo)), 403, "connection_required")


@pytest.mark.req("DM-012", "SAFE-002", "ADM-002")
def test_report_a_message_and_staff_removal(app: LiveApp) -> None:  # noqa: F811
    ana, _, bo, _, conversation = _pair(app)
    message = _sent(app, ana, conversation, "Send me your passport number")
    outsider, _ = _user(app)
    _problem(
        app.client.post(
            "/v1/reports",
            headers=_auth(outsider),
            json={"target_type": "message", "target_id": message["id"], "reason": "scam"},
        ),
        404,
        "not_found",
    )
    report = app.client.post(
        "/v1/reports",
        headers=_auth(bo),
        json={"target_type": "message", "target_id": message["id"], "reason": "scam"},
    )
    assert report.status_code == 202, report.text

    moderator, _ = _staff(app)
    queue = app.client.get(
        "/v1/admin/reports", headers=_admin(moderator), params={"limit": 100}
    ).json()
    [filed] = [r for r in queue["data"] if r["target_id"] == message["id"]]
    assert filed["evidence"]["body"] == "Send me your passport number"
    action = app.client.post(
        "/v1/admin/moderation-actions",
        headers={**_admin(moderator), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "target_type": "message",
            "target_id": message["id"],
            "action": "remove_content",
            "reason_code": "scam",
        },
    )
    assert action.status_code == 201, action.text
    [removed] = _messages(app, bo, conversation)["data"]
    assert removed["moderation_state"] == "removed_by_admin"
    assert removed["body"] is None
    _tick(app)
    [notice] = [n for n in _notifications(app, ana) if n["type"] == "moderation_notice"]
    assert notice["entity_id"] == message["id"]
    assert notice["body"] in MODERATION_BODIES["removed_message"].values()


@pytest.mark.req("AUTH-010")
def test_messages_of_deleted_accounts_lose_their_content(app: LiveApp) -> None:  # noqa: F811
    ana, ana_id, bo, _, conversation = _pair(app)
    _sent(app, ana, conversation, "Personal details here")
    _sent(app, bo, conversation, "Reply")
    db_scalar(app.db_url, "DELETE FROM users WHERE id = :u RETURNING 1", u=uuid.UUID(ana_id))
    shown = _messages(app, bo, conversation)["data"]
    assert next((m["sender"], m["body"]) for m in shown) == (None, None)
    assert shown[1]["body"] == "Reply"
    conversation_view = _conversation(app, bo, conversation)
    assert conversation_view["counterpart"] is None
    assert conversation_view["send_restriction"] == "connection_required"

    db_scalar(
        app.db_url,
        "UPDATE periodic_tasks SET next_run_at = now() - interval '1 second' "
        "WHERE name = 'retention.messaging' RETURNING 1",
    )
    _tick(app)
    db_scalar(
        app.db_url,
        "UPDATE periodic_tasks SET next_run_at = now() - interval '1 second' "
        "WHERE name = 'retention.messaging' RETURNING 1",
    )
    _tick(app)
    _tick(app)
    assert (
        db_scalar(
            app.db_url,
            "SELECT count(*) FROM messages WHERE conversation_id = :c AND sender_id IS NULL "
            "AND body IS NOT NULL",
            c=uuid.UUID(conversation),
        )
        == 0
    )


def test_turning_direct_messages_off_keeps_history_readable(app: LiveApp) -> None:  # noqa: F811
    from datetime import UTC, datetime

    from fastapi.testclient import TestClient

    from app.core.time import FixedClock
    from app.main import create_app
    from tests.conftest import make_identity_settings, make_settings

    ana, _, bo, bo_id, conversation = _pair(app)
    _sent(app, ana, conversation, "Before the switch")

    async def ok() -> bool:
        return True

    off = create_app(
        make_settings(
            database_url=app.db_url, dev_idp_enabled=True, feature_flags={"direct_messages": False}
        ),
        identity_settings=make_identity_settings(),
        readiness_checks={"db": ok},
        clock=FixedClock(datetime.now(tz=UTC).replace(microsecond=0)),
    )
    with TestClient(off, raise_server_exceptions=False) as client:
        live = LiveApp(client=client, clock=app.clock, db_url=app.db_url)
        refused = _send(live, bo, conversation, "After the switch")
        _problem(refused, 403, "feature_disabled")
        assert refused.json()["feature_key"] == "direct_messages"
        assert [m["body"] for m in _messages(live, bo, conversation)["data"]] == [
            "Before the switch"
        ]
        _problem(_open(live, bo, bo_id), 403, "feature_disabled")
