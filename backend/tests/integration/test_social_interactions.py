"""Reactions, comments, bookmarks, shares and follows against PostgreSQL (BL-1.11)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import _create, _problem, _tick, _user, app  # noqa: F401

pytestmark = pytest.mark.integration


def _post_counts(live: LiveApp, token: str, post_id: str) -> dict[str, Any]:
    response = live.client.get(f"/v1/posts/{post_id}", headers=_auth(token))
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _comment(live: LiveApp, token: str, post_id: str, key: str | None = None, **body: Any) -> Any:
    return live.client.post(
        f"/v1/posts/{post_id}/comments",
        headers={**_auth(token), "Idempotency-Key": key or str(uuid.uuid4())},
        json={"body": "Lovely spot!", **body},
    )


# ─────────────────────────────── reactions ───────────────────────────────


@pytest.mark.req("POST-005")
def test_reactions_are_one_per_user_and_changeable(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    fan, _ = _user(app)
    post = _create(app, author).json()

    liked = app.client.post(
        f"/v1/posts/{post['id']}/reactions", headers=_auth(fan), json={"reaction": "like"}
    )
    assert liked.status_code == 200, liked.text
    assert_matches_contract(liked.json(), "ReactionResult")
    assert liked.json()["counts"]["reactions"] == 1
    loved = app.client.post(
        f"/v1/posts/{post['id']}/reactions", headers=_auth(fan), json={"reaction": "love"}
    )
    again = app.client.post(
        f"/v1/posts/{post['id']}/reactions", headers=_auth(fan), json={"reaction": "love"}
    )
    assert loved.json()["counts"]["reactions"] == again.json()["counts"]["reactions"] == 1
    assert again.json()["counts"]["reactions_by_type"] == {"love": 1}

    seen = _post_counts(app, fan, post["id"])
    assert seen["viewer"]["reaction"] == "love"
    assert seen["counts"]["reactions_by_type"] == {"love": 1}
    listing = app.client.get(f"/v1/posts/{post['id']}/reactions", headers=_auth(author))
    assert_matches_contract(listing.json(), "ReactionPage")
    assert [r["reaction"] for r in listing.json()["data"]] == ["love"]

    assert (
        app.client.delete(f"/v1/posts/{post['id']}/reactions/me", headers=_auth(fan)).status_code
        == 204
    )
    assert (
        app.client.delete(f"/v1/posts/{post['id']}/reactions/me", headers=_auth(fan)).status_code
        == 204
    )
    assert _post_counts(app, author, post["id"])["counts"]["reactions"] == 0


@pytest.mark.security
def test_cannot_interact_with_invisible_posts(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    stranger, _ = _user(app)
    private = _create(app, author, visibility="private").json()
    for method, path, body in (
        ("post", f"/v1/posts/{private['id']}/reactions", {"reaction": "like"}),
        ("put", f"/v1/posts/{private['id']}/bookmark", None),
        ("get", f"/v1/posts/{private['id']}/comments", None),
    ):
        response = getattr(app.client, method)(
            path, headers=_auth(stranger), **({"json": body} if body else {})
        )
        _problem(response, 404, "not_found")
    _problem(_comment(app, stranger, private["id"]), 404, "not_found")


# ─────────────────────────────── comments ───────────────────────────────


@pytest.mark.req("POST-005")
def test_comments_replies_and_tombstones(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    commenter, _ = _user(app)
    post = _create(app, author).json()

    key = str(uuid.uuid4())
    created = _comment(app, commenter, post["id"], key)
    assert created.status_code == 201, created.text
    assert_matches_contract(created.json(), "Comment")
    replay = _comment(app, commenter, post["id"], key)
    assert replay.headers.get("Idempotent-Replayed") == "true"
    assert replay.json()["id"] == created.json()["id"]
    _problem(
        _comment(app, commenter, post["id"], key, body="Different"), 409, "idempotency_key_reused"
    )

    top = created.json()
    reply = _comment(app, author, post["id"], parent_comment_id=top["id"], body="Thanks!")
    assert reply.status_code == 201
    nested = _comment(app, commenter, post["id"], parent_comment_id=reply.json()["id"])
    _problem(nested, 422, "validation_failed")

    listing = app.client.get(f"/v1/posts/{post['id']}/comments", headers=_auth(author)).json()
    assert_matches_contract(listing, "CommentPage")
    assert [c["id"] for c in listing["data"]] == [top["id"]]
    assert listing["data"][0]["reply_count"] == 1
    replies = app.client.get(f"/v1/comments/{top['id']}/replies", headers=_auth(commenter)).json()
    assert [r["body"] for r in replies["data"]] == ["Thanks!"]
    assert _post_counts(app, author, post["id"])["counts"]["comments"] == 2

    edited = app.client.patch(
        f"/v1/comments/{top['id']}", headers=_auth(commenter), json={"body": "Edited"}
    )
    assert edited.status_code == 200
    assert edited.json()["edited_at"] is not None
    _problem(
        app.client.patch(f"/v1/comments/{top['id']}", headers=_auth(author), json={"body": "x"}),
        404,
        "not_found",
    )

    # The post's author may delete comments on their post; a tombstone remains.
    assert app.client.delete(f"/v1/comments/{top['id']}", headers=_auth(author)).status_code == 204
    after = app.client.get(f"/v1/posts/{post['id']}/comments", headers=_auth(commenter)).json()
    tombstone = after["data"][0]
    assert_matches_contract(tombstone, "Comment")
    assert (tombstone["deleted"], tombstone["body"], tombstone["author"]) == (True, None, None)
    assert _post_counts(app, author, post["id"])["counts"]["comments"] == 1


@pytest.mark.security
def test_unverified_users_cannot_comment(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    unverified, _ = _user(app, verified=False)
    post = _create(app, author).json()
    _problem(_comment(app, unverified, post["id"]), 403, "email_unverified")


# ─────────────────────────────── bookmarks & shares ───────────────────────────────


@pytest.mark.req("POST-005")
def test_bookmarks(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    reader, _ = _user(app)
    post = _create(app, author).json()
    for _ in range(2):
        assert (
            app.client.put(f"/v1/posts/{post['id']}/bookmark", headers=_auth(reader)).status_code
            == 204
        )
    assert _post_counts(app, author, post["id"])["counts"]["bookmarks"] == 1
    mine = app.client.get("/v1/users/me/bookmarks", headers=_auth(reader)).json()
    assert_matches_contract(mine, "PostPage")
    assert [p["id"] for p in mine["data"]] == [post["id"]]
    assert mine["data"][0]["viewer"]["bookmarked"] is True
    assert (
        app.client.delete(f"/v1/posts/{post['id']}/bookmark", headers=_auth(reader)).status_code
        == 204
    )
    assert app.client.get("/v1/users/me/bookmarks", headers=_auth(reader)).json()["data"] == []


@pytest.mark.req("POST-005", "AUTH-012")
def test_only_public_posts_can_be_shared(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    public = _create(app, author).json()
    private = _create(app, author, visibility="private").json()
    shared = app.client.post(
        f"/v1/posts/{public['id']}/shares", headers=_auth(author), json={"channel": "copy_link"}
    )
    assert shared.status_code == 201, shared.text
    assert_matches_contract(shared.json(), "ShareLink")
    assert shared.json()["url"].endswith(f"/stories/{public['id']}")
    assert _post_counts(app, author, public["id"])["counts"]["shares"] == 1
    _problem(
        app.client.post(f"/v1/posts/{private['id']}/shares", headers=_auth(author)),
        403,
        "forbidden",
    )


# ─────────────────────────────── follows ───────────────────────────────


@pytest.mark.req("POST-006", "POST-008")
def test_following_unlocks_followers_only_posts(app: LiveApp) -> None:  # noqa: F811
    author, author_id = _user(app)
    follower, follower_id = _user(app)
    post = _create(app, author, visibility="followers").json()
    _problem(app.client.get(f"/v1/posts/{post['id']}", headers=_auth(follower)), 404, "not_found")

    followed = app.client.put(f"/v1/users/{author_id}/follow", headers=_auth(follower))
    assert followed.status_code == 200
    assert_matches_contract(followed.json(), "FollowState")
    assert followed.json()["status"] == "following"
    assert app.client.get(f"/v1/posts/{post['id']}", headers=_auth(follower)).status_code == 200
    followers = app.client.get(f"/v1/users/{author_id}/followers", headers=_auth(author)).json()
    assert_matches_contract(followers, "UserSummaryPage")
    assert [u["id"] for u in followers["data"]] == [follower_id]
    following = app.client.get(f"/v1/users/{follower_id}/following", headers=_auth(follower)).json()
    assert [u["id"] for u in following["data"]] == [author_id]

    assert (
        app.client.delete(f"/v1/users/{author_id}/follow", headers=_auth(follower)).status_code
        == 204
    )
    _problem(app.client.get(f"/v1/posts/{post['id']}", headers=_auth(follower)), 404, "not_found")


@pytest.mark.req("POST-006", "PROF-004")
def test_private_accounts_use_follow_requests(app: LiveApp) -> None:  # noqa: F811
    owner, owner_id = _user(app)
    asker, asker_id = _user(app)
    other, other_id = _user(app)
    app.client.patch("/v1/users/me", headers=_auth(owner), json={"account_visibility": "private"})
    _tick(app)
    post = _create(app, owner).json()  # public post on a private account

    requested = app.client.put(f"/v1/users/{owner_id}/follow", headers=_auth(asker))
    assert requested.json()["status"] == "requested"
    _problem(app.client.get(f"/v1/posts/{post['id']}", headers=_auth(asker)), 404, "not_found")
    _problem(
        app.client.get(f"/v1/users/{owner_id}/followers", headers=_auth(asker)), 403, "forbidden"
    )
    pending = app.client.get("/v1/users/me/follow-requests", headers=_auth(owner)).json()
    assert [u["id"] for u in pending["data"]] == [asker_id]

    approve = app.client.post(
        f"/v1/users/me/follow-requests/{asker_id}/approve", headers=_auth(owner)
    )
    assert approve.status_code == 204
    assert app.client.get(f"/v1/posts/{post['id']}", headers=_auth(asker)).status_code == 200
    _problem(
        app.client.post(f"/v1/users/me/follow-requests/{asker_id}/approve", headers=_auth(owner)),
        404,
        "not_found",
    )

    app.client.put(f"/v1/users/{owner_id}/follow", headers=_auth(other))
    decline = app.client.post(
        f"/v1/users/me/follow-requests/{other_id}/decline", headers=_auth(owner)
    )
    assert decline.status_code == 204
    assert (
        db_scalar(
            app.db_url, "SELECT count(*) FROM follows WHERE follower_id = :u", u=uuid.UUID(other_id)
        )
        == 0
    )

    # Going public approves whatever is still pending.
    app.client.put(f"/v1/users/{owner_id}/follow", headers=_auth(other))
    app.client.patch("/v1/users/me", headers=_auth(owner), json={"account_visibility": "public"})
    _tick(app)
    assert (
        db_scalar(
            app.db_url,
            "SELECT status FROM follows WHERE follower_id = :u AND followee_id = :o",
            u=uuid.UUID(other_id),
            o=uuid.UUID(owner_id),
        )
        == "active"
    )


def test_follow_validation(app: LiveApp) -> None:  # noqa: F811
    me, my_id = _user(app)
    _problem(
        app.client.put(f"/v1/users/{my_id}/follow", headers=_auth(me)), 422, "validation_failed"
    )
    _problem(
        app.client.put(f"/v1/users/{uuid.uuid4()}/follow", headers=_auth(me)), 404, "not_found"
    )
