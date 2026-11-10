"""Feed against PostgreSQL: fallback chain, tabs, filters, snapshots, safety (BL-1.13)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import (  # noqa: F401
    _create,
    _destination,
    _problem,
    _user,
    app,
)

pytestmark = pytest.mark.integration


def _feed(live: LiveApp, token: str, **params: Any) -> dict[str, Any]:
    response = live.client.get("/v1/feed", headers=_auth(token), params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    assert_matches_contract(body, "FeedPage")
    return body


def _ids(body: dict[str, Any]) -> list[str]:
    return [p["id"] for p in body["data"]]


def _post_in(live: LiveApp, token: str, path: str | None, **overrides: Any) -> str:
    if path is None:
        response = _create(live, token, **overrides)
    else:
        response = _create(
            live,
            token,
            location_precision="destination",
            destination_id=_destination(live, path),
            **overrides,
        )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


# ─────────────────────────────── FEED-001 fallback chain ───────────────────────────────


@pytest.mark.req("FEED-001")
def test_a_new_user_never_sees_an_empty_feed(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    _post_in(app, author, None, body="A tip for everyone")
    newcomer, _ = _user(app)
    body = _feed(app, newcomer)
    assert body["data"], "global fallback must not be empty"
    assert body["context"]["source"] == "global"
    assert body["context"]["destination"] is None


@pytest.mark.req("FEED-001", "LOC-002", "LOC-006")
def test_browse_destination_feeds_include_descendants(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    copacabana_post = _post_in(
        app, author, "brazil/rio-de-janeiro/copacabana", body="Sunrise on Copacabana"
    )
    rio_post = _post_in(app, author, "brazil/rio-de-janeiro", body="Rio by tram")
    elsewhere = _post_in(app, author, "japan/kyoto", body="Temples in Kyoto")
    reader, _ = _user(app)
    app.client.put(
        "/v1/users/me/browse-destination",
        headers=_auth(reader),
        json={"destination_id": _destination(app, "brazil/rio-de-janeiro")},
    )
    body = _feed(app, reader)
    assert body["context"]["source"] == "selected"
    assert body["context"]["destination"]["path"] == "brazil/rio-de-janeiro"
    ids = _ids(body)
    assert {copacabana_post, rio_post} <= set(ids)
    assert elsewhere not in ids


@pytest.mark.req("FEED-001")
def test_upcoming_trips_and_interests_are_later_fallbacks(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    _post_in(app, author, "france/paris", body="Croissants at dawn")
    _post_in(app, author, None, body="Cheap eats guide", tags=["street food"])
    planner, _ = _user(app)
    app.client.post(
        "/v1/users/me/upcoming-destinations",
        headers=_auth(planner),
        json={"destination_id": _destination(app, "france/paris")},
    )
    assert _feed(app, planner)["context"]["source"] == "upcoming_trip"
    foodie, _ = _user(app)
    app.client.patch("/v1/users/me", headers=_auth(foodie), json={"interests": ["Street food"]})
    assert _feed(app, foodie)["context"]["source"] == "interests"


def test_an_explicit_quiet_destination_stays_empty(app: LiveApp) -> None:  # noqa: F811
    reader, _ = _user(app)
    body = _feed(app, reader, destination_id=_destination(app, "iceland/reykjavik"))
    assert body["context"]["source"] == "selected"
    assert body["data"] == []
    _problem(
        app.client.get(
            "/v1/feed", headers=_auth(reader), params={"destination_id": str(uuid.uuid4())}
        ),
        404,
        "not_found",
    )


# ─────────────────────────────── tabs & filters ───────────────────────────────


@pytest.mark.req("FEED-002", "POST-008")
def test_following_tab_shows_followed_authors_including_followers_only(app: LiveApp) -> None:  # noqa: F811
    author, author_id = _user(app)
    secret = _post_in(app, author, None, visibility="followers", body="For my followers")
    reader, _ = _user(app)
    assert secret not in _ids(_feed(app, reader, tab="following"))
    app.client.put(f"/v1/users/{author_id}/follow", headers=_auth(reader))
    body = _feed(app, reader, tab="following")
    assert body["context"]["source"] == "following"
    assert secret in _ids(body)


@pytest.mark.req("FEED-003", "I18N-005", "POST-011")
def test_category_tag_and_language_filters(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    rome = _destination(app, "italy/rome")
    review = _post_in(app, author, "italy/rome", kind="review", rating=4, body="Great pasta")
    tagged = _post_in(app, author, "italy/rome", body="Gelato crawl", tags=["gelato"])
    german = _post_in(app, author, "italy/rome", body="Kolosseum am Morgen", language="de")
    reader, _ = _user(app)
    assert _ids(_feed(app, reader, destination_id=rome, category="review")) == [review]
    assert _ids(_feed(app, reader, destination_id=rome, tag="gelato")) == [tagged]
    assert _ids(_feed(app, reader, destination_id=rome, language="de")) == [german]
    _problem(
        app.client.get("/v1/feed", headers=_auth(reader), params={"category": "meme"}),
        422,
        "validation_failed",
    )


def test_nearby_needs_a_location(app: LiveApp) -> None:  # noqa: F811
    reader, _ = _user(app)
    _problem(
        app.client.get("/v1/feed", headers=_auth(reader), params={"tab": "nearby"}),
        422,
        "validation_failed",
    )


@pytest.mark.req("FEED-002", "LOC-005")
def test_nearby_tab_uses_the_city_around_the_device(app: LiveApp) -> None:  # noqa: F811
    if not db_scalar(app.db_url, "SELECT to_regclass('destination_boundaries') IS NOT NULL"):
        pytest.skip("PostGIS not installed on this PostgreSQL (runs in CI)")
    author, _ = _user(app)
    post = _post_in(app, author, "brazil/rio-de-janeiro/ipanema")
    reader, _ = _user(app)
    body = _feed(app, reader, tab="nearby", near="-22.9711,-43.1822", radius_km=5)
    assert body["context"]["source"] == "gps"
    assert body["context"]["destination"]["path"] == "brazil/rio-de-janeiro"
    assert body["context"]["radius_km"] == 5
    assert post in _ids(body)


# ─────────────────────────────── snapshots (FEED-004) ───────────────────────────────


@pytest.mark.req("FEED-004")
def test_pages_are_stable_while_new_posts_arrive(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    for i in range(12):
        _post_in(app, author, "peru/cusco", body=f"Cusco note {i}")
    other, _ = _user(app)
    for i in range(12):
        _post_in(app, other, "peru/cusco", body=f"Another Cusco note {i}")
    reader, _ = _user(app)
    cusco = _destination(app, "peru/cusco")
    first = _feed(app, reader, destination_id=cusco, limit=10)
    _post_in(app, author, "peru/cusco", body="Brand new arrival")
    second = _feed(app, reader, destination_id=cusco, limit=10, cursor=first["page"]["next_cursor"])
    assert not set(_ids(first)) & set(_ids(second))
    assert second["page"]["reset"] is False

    db_scalar(
        app.db_url, "UPDATE feed_sessions SET expires_at = now() - interval '1 minute' RETURNING 1"
    )
    expired = _feed(
        app, reader, destination_id=cusco, limit=10, cursor=second["page"]["next_cursor"]
    )
    assert expired["page"]["reset"] is True


# ─────────────────────────────── safety & feedback ───────────────────────────────


@pytest.mark.req("FEED-005", "SAFE-001")
@pytest.mark.security
def test_blocked_authors_are_excluded(app: LiveApp) -> None:  # noqa: F811
    troll, troll_id = _user(app)
    post = _post_in(app, troll, "spain/barcelona")
    reader, _ = _user(app)
    barcelona = _destination(app, "spain/barcelona")
    assert post in _ids(_feed(app, reader, destination_id=barcelona))
    app.client.put(f"/v1/users/{troll_id}/block", headers=_auth(reader))
    assert post not in _ids(_feed(app, reader, destination_id=barcelona))


@pytest.mark.req("FEED-007")
def test_hidden_posts_never_come_back(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    post = _post_in(app, author, "morocco/marrakesh")
    reader, _ = _user(app)
    marrakesh = _destination(app, "morocco/marrakesh")
    assert post in _ids(_feed(app, reader, destination_id=marrakesh))
    hidden = app.client.post(
        "/v1/feed/feedback", headers=_auth(reader), json={"post_id": post, "kind": "hide"}
    )
    assert hidden.status_code == 204
    again = app.client.post(
        "/v1/feed/feedback", headers=_auth(reader), json={"post_id": post, "kind": "hide"}
    )
    assert again.status_code == 204
    assert post not in _ids(_feed(app, reader, destination_id=marrakesh))
    _problem(
        app.client.post(
            "/v1/feed/feedback",
            headers=_auth(reader),
            json={"post_id": str(uuid.uuid4()), "kind": "hide"},
        ),
        404,
        "not_found",
    )


@pytest.mark.req("FEED-006")
def test_author_diversity_on_a_page(app: LiveApp) -> None:  # noqa: F811
    prolific, prolific_id = _user(app)
    for i in range(6):
        _post_in(app, prolific, "thailand/bangkok", body=f"Bangkok street {i}")
    for _ in range(4):
        other, _ = _user(app)
        for i in range(3):
            _post_in(app, other, "thailand/bangkok", body=f"Bangkok {uuid.uuid4().hex[:6]} {i}")
    reader, _ = _user(app)
    page = _feed(app, reader, destination_id=_destination(app, "thailand/bangkok"), limit=10)
    authors = [p["author"]["id"] for p in page["data"]]
    assert authors.count(prolific_id) <= 2
