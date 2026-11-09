"""In-app notification center (BL-1.16, NOTIF-001): created from domain events through the job
queue, localized at read time, deduplicated, respecting preferences and blocks."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_moderation import _admin, _staff
from tests.integration.test_posts import _create, _problem, _tick, _user, app  # noqa: F401
from tests.integration.test_social_interactions import _comment

pytestmark = [pytest.mark.integration, pytest.mark.req("NOTIF-001")]

EN = {"Accept-Language": "en"}


def _inbox(live: LiveApp, token: str, **params: Any) -> dict[str, Any]:
    headers = {**_auth(token), **params.pop("headers", EN)}
    response = live.client.get("/v1/notifications", headers=headers, params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert_matches_contract(body, "NotificationPage")
    return body


def _unread(live: LiveApp, token: str) -> int:
    response = live.client.get("/v1/notifications/unread-count", headers=_auth(token))
    assert response.status_code == 200
    return int(response.json()["count"])


def _react(live: LiveApp, token: str, post_id: str, reaction: str = "like") -> None:
    response = live.client.post(
        f"/v1/posts/{post_id}/reactions", headers=_auth(token), json={"reaction": reaction}
    )
    assert response.status_code == 200, response.text


def test_reactions_and_comments_notify_the_author(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    fan, fan_id = _user(app)
    post = _create(app, author).json()
    _react(app, fan, post["id"])
    comment = _comment(app, fan, post["id"]).json()
    _react(app, author, post["id"])  # own activity never notifies
    _tick(app)

    inbox = _inbox(app, author)
    assert [n["type"] for n in inbox["data"]] == ["post_comment", "post_reaction"]
    commented, reacted = inbox["data"]
    assert commented["actor"]["id"] == fan_id
    assert commented["title"] == "New comment"
    assert commented["body"] == f"{commented['actor']['display_name']} commented on your post."
    assert commented["entity_type"] == "post"
    assert commented["entity_id"] == post["id"]
    assert commented["data"] == {"post_id": post["id"], "comment_id": comment["id"]}
    assert reacted["data"] == {"post_id": post["id"], "reaction": "like"}
    assert commented["read_at"] is None
    assert _unread(app, author) == 2
    assert _inbox(app, fan)["data"] == []


def test_repeated_reactions_notify_once(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    fan, _ = _user(app)
    post = _create(app, author).json()
    _react(app, fan, post["id"])
    _tick(app)
    app.client.delete(f"/v1/posts/{post['id']}/reactions/me", headers=_auth(fan))
    _react(app, fan, post["id"], "love")
    _tick(app)
    assert [n["type"] for n in _inbox(app, author)["data"]] == ["post_reaction"]


def test_follows_and_follow_requests_notify(app: LiveApp) -> None:  # noqa: F811
    public, public_id = _user(app)
    private, private_id = _user(app)
    app.client.patch("/v1/users/me", headers=_auth(private), json={"account_visibility": "private"})
    fan, fan_id = _user(app)
    app.client.put(f"/v1/users/{public_id}/follow", headers=_auth(fan))
    app.client.put(f"/v1/users/{private_id}/follow", headers=_auth(fan))
    _tick(app)
    [follower] = _inbox(app, public)["data"]
    assert (follower["type"], follower["title"]) == ("new_follower", "New follower")
    assert follower["entity_type"] == "user"
    assert follower["entity_id"] == fan_id
    [request] = _inbox(app, private)["data"]
    assert request["type"] == "follow_request"
    assert request["body"].endswith("wants to follow you.")


def test_text_is_localized_for_the_reader(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)  # registered with locale pt-BR (see _register)
    fan, _ = _user(app)
    post = _create(app, author).json()
    _react(app, fan, post["id"])
    _tick(app)
    [own_locale] = _inbox(app, author, headers={})["data"]
    assert own_locale["title"] == "Nova reação"
    [german] = _inbox(app, author, headers={"Accept-Language": "de-AT, en;q=0.5"})["data"]
    assert german["title"] == "Neue Reaktion"
    assert german["body"].endswith("hat auf deinen Beitrag reagiert.")


def test_muted_types_are_not_created(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    fan, _ = _user(app)
    muted = app.client.patch(
        "/v1/users/me/preferences",
        headers=_auth(author),
        json={"notification_settings": {"post_comment": {"in_app": False}}},
    )
    assert muted.status_code == 200, muted.text
    post = _create(app, author).json()
    _comment(app, fan, post["id"])
    _react(app, fan, post["id"])
    _tick(app)
    assert [n["type"] for n in _inbox(app, author)["data"]] == ["post_reaction"]


@pytest.mark.req("NOTIF-001", "SAFE-001")
@pytest.mark.security
def test_blocking_hides_existing_notifications_from_that_person(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    fan, fan_id = _user(app)
    other, _ = _user(app)
    post = _create(app, author).json()
    _react(app, fan, post["id"])
    _react(app, other, post["id"])
    _tick(app)
    assert _unread(app, author) == 2
    assert app.client.put(f"/v1/users/{fan_id}/block", headers=_auth(author)).status_code == 204
    actors = [n["actor"]["id"] for n in _inbox(app, author)["data"]]
    assert len(actors) == 1
    assert fan_id not in actors
    assert _unread(app, author) == 1


def test_mark_read_by_ids_or_all(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    post = _create(app, author).json()
    for _ in range(3):
        fan, _ = _user(app)
        _react(app, fan, post["id"])
    _tick(app)
    newest, *rest = _inbox(app, author)["data"]
    snoop, _ = _user(app)
    # Someone else's IDs are ignored silently.
    stranger = app.client.post(
        "/v1/notifications/read", headers=_auth(snoop), json={"ids": [newest["id"]]}
    )
    assert stranger.status_code == 204
    assert _unread(app, author) == 3

    marked = app.client.post(
        "/v1/notifications/read", headers=_auth(author), json={"ids": [newest["id"]]}
    )
    assert marked.status_code == 204
    assert _unread(app, author) == 2
    unread = _inbox(app, author, unread_only="true")["data"]
    assert [n["id"] for n in unread] == [n["id"] for n in rest]
    assert _inbox(app, author)["data"][0]["read_at"] is not None

    assert (
        app.client.post(
            "/v1/notifications/read", headers=_auth(author), json={"all": True}
        ).status_code
        == 204
    )
    assert _unread(app, author) == 0


@pytest.mark.parametrize(
    "body",
    [{}, {"ids": []}, {"all": False}, {"ids": [str(uuid.uuid4())], "all": True}, {"x": 1}],
)
def test_mark_read_validates_its_body(app: LiveApp, body: dict[str, Any]) -> None:  # noqa: F811
    token, _ = _user(app)
    _problem(
        app.client.post("/v1/notifications/read", headers=_auth(token), json=body),
        422,
        "validation_failed",
    )


def test_notifications_page_with_a_cursor(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    post = _create(app, author).json()
    for _ in range(3):
        fan, _ = _user(app)
        _react(app, fan, post["id"])
    _tick(app)
    first = _inbox(app, author, limit=2)
    assert len(first["data"]) == 2
    assert first["page"]["has_more"] is True
    second = _inbox(app, author, limit=2, cursor=first["page"]["next_cursor"])
    assert len(second["data"]) == 1
    assert second["page"] == {"next_cursor": None, "has_more": False}
    ids = [n["id"] for n in first["data"] + second["data"]]
    assert len(set(ids)) == 3


@pytest.mark.req("NOTIF-001", "SAFE-013")
def test_moderation_actions_notify_the_affected_author(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    post = _create(app, author).json()
    moderator, _ = _staff(app)
    removed = app.client.post(
        "/v1/admin/moderation-actions",
        headers=_admin(moderator, **{"Idempotency-Key": str(uuid.uuid4())}),
        json={
            "target_type": "post",
            "target_id": post["id"],
            "action": "remove_content",
            "reason_code": "spam",
        },
    )
    assert removed.status_code == 201, removed.text
    _tick(app)
    [notice] = _inbox(app, author)["data"]
    assert notice["type"] == "moderation_notice"
    assert notice["actor"] is None  # staff stay anonymous
    assert notice["title"] == "Community guidelines"
    assert notice["body"].startswith("One of your posts was removed")
    assert notice["data"] == {
        "action": "remove_content",
        "target_type": "post",
        "target_id": post["id"],
    }
