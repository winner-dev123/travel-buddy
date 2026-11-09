"""Blocking against PostgreSQL: immediate, bidirectional, silent (BL-1.12, SAFE-001)."""

from __future__ import annotations

import uuid

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import _create, _problem, _user, app  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.security]


def _comment(live: LiveApp, token: str, post_id: str, body: str) -> None:
    response = live.client.post(
        f"/v1/posts/{post_id}/comments",
        headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())},
        json={"body": body},
    )
    assert response.status_code == 201, response.text


@pytest.mark.req("SAFE-001")
def test_block_is_immediate_bidirectional_and_removes_follows(app: LiveApp) -> None:  # noqa: F811
    alice, alice_id = _user(app)
    bob, bob_id = _user(app)
    post_by_alice = _create(app, alice).json()
    post_by_bob = _create(app, bob).json()
    app.client.put(f"/v1/users/{alice_id}/follow", headers=_auth(bob))
    app.client.put(f"/v1/users/{bob_id}/follow", headers=_auth(alice))

    assert app.client.put(f"/v1/users/{bob_id}/block", headers=_auth(alice)).status_code == 204
    assert (
        app.client.put(f"/v1/users/{bob_id}/block", headers=_auth(alice)).status_code == 204
    )  # idempotent
    follows = db_scalar(
        app.db_url,
        "SELECT count(*) FROM follows WHERE follower_id IN (:a, :b) AND followee_id IN (:a, :b)",
        a=uuid.UUID(alice_id),
        b=uuid.UUID(bob_id),
    )
    assert follows == 0

    # Each side loses the other's content, in both directions.
    _problem(
        app.client.get(f"/v1/posts/{post_by_alice['id']}", headers=_auth(bob)), 404, "not_found"
    )
    _problem(
        app.client.get(f"/v1/posts/{post_by_bob['id']}", headers=_auth(alice)), 404, "not_found"
    )
    _problem(app.client.get(f"/v1/users/{alice_id}/posts", headers=_auth(bob)), 404, "not_found")
    # The blocked user cannot follow back and learns nothing.
    _problem(app.client.put(f"/v1/users/{alice_id}/follow", headers=_auth(bob)), 404, "not_found")
    _problem(
        app.client.get(f"/v1/users/{alice_id}/followers", headers=_auth(bob)), 404, "not_found"
    )

    blocks = app.client.get("/v1/users/me/blocks", headers=_auth(alice))
    assert_matches_contract(blocks.json(), "UserSummaryPage")
    assert [u["id"] for u in blocks.json()["data"]] == [bob_id]
    assert app.client.get("/v1/users/me/blocks", headers=_auth(bob)).json()["data"] == []

    # Unblocking restores visibility but not follows.
    assert app.client.delete(f"/v1/users/{bob_id}/block", headers=_auth(alice)).status_code == 204
    assert app.client.get(f"/v1/posts/{post_by_alice['id']}", headers=_auth(bob)).status_code == 200
    assert (
        db_scalar(
            app.db_url, "SELECT count(*) FROM follows WHERE follower_id = :b", b=uuid.UUID(bob_id)
        )
        == 0
    )


@pytest.mark.req("SAFE-001")
def test_blocked_users_disappear_from_comments_and_reactions(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    viewer, viewer_id = _user(app)
    troll, troll_id = _user(app)
    post = _create(app, author).json()
    _comment(app, troll, post["id"], "Rude remark")
    _comment(app, author, post["id"], "Thanks everyone")
    app.client.post(
        f"/v1/posts/{post['id']}/reactions", headers=_auth(troll), json={"reaction": "wow"}
    )

    app.client.put(f"/v1/users/{troll_id}/block", headers=_auth(viewer))
    comments = app.client.get(f"/v1/posts/{post['id']}/comments", headers=_auth(viewer)).json()
    assert [c["body"] for c in comments["data"]] == ["Thanks everyone"]
    reactions = app.client.get(f"/v1/posts/{post['id']}/reactions", headers=_auth(viewer)).json()
    assert reactions["data"] == []
    # The troll is hidden from the viewer only; others still see the comment.
    everyone = app.client.get(f"/v1/posts/{post['id']}/comments", headers=_auth(author)).json()
    assert len(everyone["data"]) == 2
    # And the blocked user no longer sees the blocker's comments either.
    _comment(app, viewer, post["id"], "Lovely")
    seen_by_troll = app.client.get(f"/v1/posts/{post['id']}/comments", headers=_auth(troll)).json()
    assert "Lovely" not in [c["body"] for c in seen_by_troll["data"]]
    assert viewer_id


def test_block_validation(app: LiveApp) -> None:  # noqa: F811
    me, my_id = _user(app)
    _problem(
        app.client.put(f"/v1/users/{my_id}/block", headers=_auth(me)), 422, "validation_failed"
    )
    _problem(app.client.put(f"/v1/users/{uuid.uuid4()}/block", headers=_auth(me)), 404, "not_found")
    assert (
        app.client.delete(f"/v1/users/{uuid.uuid4()}/block", headers=_auth(me)).status_code == 204
    )
