"""Posts against PostgreSQL: publish, fan-out, idempotency, visibility, edit, delete (BL-1.10)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.time import FixedClock
from app.main import create_app
from tests.conftest import make_identity_settings, make_settings
from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth, _id_token, _register

pytestmark = pytest.mark.integration

CRON = "k" * 40


@pytest.fixture
def app(catalog: str) -> Iterator[LiveApp]:  # noqa: F811
    async def ok() -> bool:
        return True

    clock = FixedClock(datetime.now(tz=UTC).replace(microsecond=0))
    application = create_app(
        make_settings(database_url=catalog, dev_idp_enabled=True, cron_secret=SecretStr(CRON)),
        identity_settings=make_identity_settings(),
        readiness_checks={"db": ok},
        clock=clock,
    )
    with TestClient(application, raise_server_exceptions=False) as client:
        yield LiveApp(client=client, clock=clock, db_url=catalog)


def _user(live: LiveApp, *, verified: bool = True) -> tuple[str, str]:
    token = _id_token(live, email_verified=verified)
    response = _register(live, token)
    assert response.status_code == 201, response.text
    body = response.json()
    return str(body["tokens"]["access_token"]), str(body["user"]["account"]["id"])


def _destination(live: LiveApp, path: str) -> str:
    return str(live.client.get("/v1/destinations/lookup", params={"path": path}).json()["id"])


def _create(live: LiveApp, token: str, key: str | None = None, **overrides: Any) -> Any:
    body: dict[str, Any] = {
        "kind": "tip",
        "body": "Go to the beach early, the light is wonderful.",
        "visibility": "public",
        "location_precision": "none",
    }
    body.update(overrides)
    headers = {**_auth(token), "Idempotency-Key": key or str(uuid.uuid4())}
    return live.client.post("/v1/posts", headers=headers, json=body)


def _problem(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()
    assert body["code"] == code
    return body


def _tick(live: LiveApp) -> dict[str, int]:
    response = live.client.post("/internal/jobs/tick", headers={"Authorization": f"Bearer {CRON}"})
    assert response.status_code == 200, response.text
    data: dict[str, int] = response.json()["data"]
    return data


# ─────────────────────────────── publish ───────────────────────────────


@pytest.mark.req("POST-001", "POST-002", "POST-003", "LOC-006")
def test_publish_with_destination_fans_out_to_ancestors(app: LiveApp) -> None:
    token, _ = _user(app)
    copacabana = _destination(app, "brazil/rio-de-janeiro/copacabana")
    response = _create(
        app,
        token,
        location_precision="destination",
        destination_id=copacabana,
        tags=["#Beach", "beach"],
    )
    assert response.status_code == 201, response.text
    post = response.json()
    assert_matches_contract(post, "Post")
    assert response.headers["Location"] == f"/v1/posts/{post['id']}"
    assert post["primary_destination"]["path"] == "brazil/rio-de-janeiro/copacabana"
    assert post["tags"] == ["beach"]
    assert post["moderation_state"] == "approved"  # visible to the author only
    assert post["viewer"]["is_author"] is True
    rows = db_scalar(
        app.db_url,
        "SELECT string_agg(d.path_segment || ':' || pd.depth_from_primary || ':' "
        "|| pd.visibility_public, ',' ORDER BY pd.depth_from_primary) "
        "FROM post_destinations pd JOIN destinations d "
        "ON d.id = pd.destination_id WHERE pd.post_id = :p",
        p=uuid.UUID(post["id"]),
    )
    assert rows == "copacabana:0:true,rio-de-janeiro:1:true,brazil:2:true"
    events = db_scalar(
        app.db_url,
        "SELECT count(*) FROM outbox_events "
        "WHERE event_type = 'post.published' AND aggregate_id = :p",
        p=uuid.UUID(post["id"]),
    )
    assert events == 1


@pytest.mark.req("SAFE-005")
def test_create_is_idempotent(app: LiveApp) -> None:
    token, _ = _user(app)
    key = str(uuid.uuid4())
    first = _create(app, token, key)
    replay = _create(app, token, key)
    assert first.status_code == replay.status_code == 201
    assert replay.headers.get("Idempotent-Replayed") == "true"
    assert replay.json()["id"] == first.json()["id"]
    assert_matches_contract(replay.json(), "Post")
    _problem(_create(app, token, key, body="A different body"), 409, "idempotency_key_reused")
    assert (
        db_scalar(
            app.db_url, "SELECT count(*) FROM posts WHERE id = :i", i=uuid.UUID(first.json()["id"])
        )
        == 1
    )
    missing = app.client.post(
        "/v1/posts",
        headers=_auth(token),
        json={"kind": "tip", "body": "x", "visibility": "public", "location_precision": "none"},
    )
    assert missing.status_code == 422


@pytest.mark.req("AUTH-004")
@pytest.mark.security
def test_unverified_email_cannot_post(app: LiveApp) -> None:
    token, _ = _user(app, verified=False)
    _problem(_create(app, token), 403, "email_unverified")


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        (
            {"kind": "review", "location_precision": "destination", "destination_id": "DEST"},
            "/rating",
        ),
        ({"rating": 4}, "/rating"),
        ({"location_precision": "none", "destination_id": "DEST"}, "/location_precision"),
        ({"location_precision": "destination"}, "/destination_id"),
        ({"media_ids": [str(uuid.uuid4())]}, "/media_ids"),
        ({"kind": "restaurant_recommendation"}, "/location_precision"),
        ({"body": "   "}, "/body"),
        (
            {"location_precision": "destination", "destination_id": str(uuid.uuid4())},
            "/destination_id",
        ),
    ],
)
def test_invalid_posts_are_rejected(app: LiveApp, overrides: dict[str, Any], field: str) -> None:
    token, _ = _user(app)
    if overrides.get("destination_id") == "DEST":
        overrides["destination_id"] = _destination(app, "portugal/lisbon")
    body = _problem(_create(app, token, **overrides), 422, "validation_failed")
    assert body["errors"][0]["field"] == field


# ─────────────────────────────── read & visibility ───────────────────────────────


@pytest.mark.req("POST-008")
@pytest.mark.security
def test_visibility_is_enforced_on_read(app: LiveApp) -> None:
    author, _ = _user(app)
    stranger, _ = _user(app)
    public = _create(app, author).json()
    private = _create(app, author, visibility="private").json()
    followers = _create(app, author, visibility="followers").json()

    seen = app.client.get(f"/v1/posts/{public['id']}", headers=_auth(stranger))
    assert seen.status_code == 200
    assert_matches_contract(seen.json(), "Post")
    assert "moderation_state" not in seen.json()
    assert seen.json()["viewer"]["can_edit"] is False
    for hidden in (private, followers):
        _problem(
            app.client.get(f"/v1/posts/{hidden['id']}", headers=_auth(stranger)), 404, "not_found"
        )
        assert app.client.get(f"/v1/posts/{hidden['id']}", headers=_auth(author)).status_code == 200


@pytest.mark.req("PROF-004")
def test_private_account_hides_public_posts_from_feeds_and_strangers(app: LiveApp) -> None:
    author, _ = _user(app)
    stranger, _ = _user(app)
    rome = _destination(app, "italy/rome")
    post = _create(app, author, location_precision="destination", destination_id=rome).json()
    app.client.patch("/v1/users/me", headers=_auth(author), json={"account_visibility": "private"})
    assert _tick(app)["succeeded"] >= 1
    listed = db_scalar(
        app.db_url,
        "SELECT bool_or(visibility_public) FROM post_destinations WHERE post_id = :p",
        p=uuid.UUID(post["id"]),
    )
    assert listed is False
    _problem(app.client.get(f"/v1/posts/{post['id']}", headers=_auth(stranger)), 404, "not_found")

    app.client.patch("/v1/users/me", headers=_auth(author), json={"account_visibility": "public"})
    _tick(app)
    assert app.client.get(f"/v1/posts/{post['id']}", headers=_auth(stranger)).status_code == 200


def test_indexable_follows_the_authors_consent(app: LiveApp) -> None:
    author, _ = _user(app)
    post = _create(app, author).json()
    assert post["indexable"] is False
    app.client.patch(
        "/v1/users/me/privacy", headers=_auth(author), json={"search_engine_indexing": True}
    )
    again = app.client.get(f"/v1/posts/{post['id']}", headers=_auth(author)).json()
    assert again["indexable"] is True


@pytest.mark.req("POST-008")
def test_user_post_list_respects_visibility_and_paginates(app: LiveApp) -> None:
    author, author_id = _user(app)
    stranger, _ = _user(app)
    for i in range(3):
        _create(app, author, body=f"Public tip {i}")
    _create(app, author, body="Only me", visibility="private")

    mine = app.client.get(f"/v1/users/{author_id}/posts", headers=_auth(author)).json()
    assert len(mine["data"]) == 4
    first = app.client.get(
        f"/v1/users/{author_id}/posts", headers=_auth(stranger), params={"limit": 2}
    )
    assert first.status_code == 200
    assert_matches_contract(first.json(), "PostPage")
    second = app.client.get(
        f"/v1/users/{author_id}/posts",
        headers=_auth(stranger),
        params={"limit": 2, "cursor": first.json()["page"]["next_cursor"]},
    ).json()
    bodies = [p["body"] for p in first.json()["data"] + second["data"]]
    assert sorted(bodies) == ["Public tip 0", "Public tip 1", "Public tip 2"]
    assert second["page"]["has_more"] is False
    unknown = app.client.get(f"/v1/users/{uuid.uuid4()}/posts", headers=_auth(stranger))
    _problem(unknown, 404, "not_found")


# ─────────────────────────────── edit & delete ───────────────────────────────


@pytest.mark.req("POST-007")
def test_edit_marks_edited_and_updates_fan_out(app: LiveApp) -> None:
    author, _ = _user(app)
    lisbon, tokyo = _destination(app, "portugal/lisbon"), _destination(app, "japan/tokyo")
    post = _create(app, author, location_precision="destination", destination_id=lisbon).json()
    assert post["edited_at"] is None

    edited = app.client.patch(
        f"/v1/posts/{post['id']}",
        headers=_auth(author),
        json={"body": "Updated tip", "destination_id": tokyo, "tags": ["ramen"]},
    )
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert_matches_contract(body, "Post")
    assert body["edited_at"] is not None
    assert body["primary_destination"]["path"] == "japan/tokyo"
    assert body["tags"] == ["ramen"]
    destinations = db_scalar(
        app.db_url,
        "SELECT string_agg(d.path_segment, ',' ORDER BY pd.depth_from_primary) "
        "FROM post_destinations pd JOIN destinations d ON d.id = pd.destination_id "
        "WHERE pd.post_id = :p",
        p=uuid.UUID(post["id"]),
    )
    assert destinations == "tokyo,japan"

    hidden = app.client.patch(
        f"/v1/posts/{post['id']}", headers=_auth(author), json={"visibility": "private"}
    )
    assert hidden.status_code == 200
    assert (
        db_scalar(
            app.db_url,
            "SELECT bool_or(visibility_public) FROM post_destinations WHERE post_id = :p",
            p=uuid.UUID(post["id"]),
        )
        is False
    )


@pytest.mark.security
def test_only_the_author_can_edit_or_delete(app: LiveApp) -> None:
    author, _ = _user(app)
    other, _ = _user(app)
    post = _create(app, author).json()
    _problem(
        app.client.patch(f"/v1/posts/{post['id']}", headers=_auth(other), json={"body": "x"}),
        404,
        "not_found",
    )
    _problem(app.client.delete(f"/v1/posts/{post['id']}", headers=_auth(other)), 404, "not_found")


@pytest.mark.req("POST-007")
def test_delete_removes_the_post_everywhere(app: LiveApp) -> None:
    author, _ = _user(app)
    paris = _destination(app, "france/paris")
    post = _create(app, author, location_precision="destination", destination_id=paris).json()
    assert app.client.delete(f"/v1/posts/{post['id']}", headers=_auth(author)).status_code == 204
    _problem(app.client.get(f"/v1/posts/{post['id']}", headers=_auth(author)), 404, "not_found")
    assert (
        db_scalar(
            app.db_url,
            "SELECT count(*) FROM post_destinations WHERE post_id = :p",
            p=uuid.UUID(post["id"]),
        )
        == 0
    )
    assert (
        db_scalar(
            app.db_url,
            "SELECT payload->>'was_public' FROM outbox_events WHERE event_type = 'post.deleted' "
            "AND aggregate_id = :p",
            p=uuid.UUID(post["id"]),
        )
        == "true"
    )
