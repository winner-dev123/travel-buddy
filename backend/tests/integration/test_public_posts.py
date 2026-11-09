"""Guest mode: anonymous public posts (AUTH-012, FEED-005, PROF-008)."""

from __future__ import annotations

import uuid

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import (  # noqa: F401
    _create,
    _destination,
    _problem,
    _tick,
    _user,
    app,
)

pytestmark = pytest.mark.integration


@pytest.mark.req("AUTH-012")
def test_guests_see_only_public_approved_posts_by_public_accounts(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    public = _create(app, author).json()
    followers = _create(app, author, visibility="followers").json()

    seen = app.client.get(f"/v1/public/posts/{public['id']}")
    assert seen.status_code == 200, seen.text
    assert_matches_contract(seen.json(), "PublicPost")
    assert "viewer" not in seen.json()
    assert "moderation_state" not in seen.json()
    assert seen.headers["Cache-Control"] == "public, max-age=60"
    _problem(app.client.get(f"/v1/public/posts/{followers['id']}"), 404, "not_found")
    _problem(app.client.get(f"/v1/public/posts/{uuid.uuid4()}"), 404, "not_found")

    app.client.patch("/v1/users/me", headers=_auth(author), json={"account_visibility": "private"})
    _tick(app)
    _problem(app.client.get(f"/v1/public/posts/{public['id']}"), 404, "not_found")


@pytest.mark.req("FEED-005", "LOC-006")
def test_destination_listing_includes_descendants_and_filters(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    ipanema = _destination(app, "brazil/rio-de-janeiro/ipanema")
    rio = _destination(app, "brazil/rio-de-janeiro")
    tip = _create(app, author, location_precision="destination", destination_id=ipanema).json()
    review = _create(
        app,
        author,
        kind="review",
        rating=5,
        location_precision="destination",
        destination_id=rio,
    ).json()

    listing = app.client.get("/v1/public/posts", params={"destination_id": rio})
    assert listing.status_code == 200, listing.text
    assert_matches_contract(listing.json(), "PublicPostPage")
    ids = {p["id"] for p in listing.json()["data"]}
    assert {tip["id"], review["id"]} <= ids
    reviews = app.client.get(
        "/v1/public/posts", params={"destination_id": rio, "category": "review"}
    ).json()
    assert {p["id"] for p in reviews["data"]} == {review["id"]}

    _problem(
        app.client.get("/v1/public/posts", params={"destination_id": str(uuid.uuid4())}),
        404,
        "not_found",
    )
    _problem(
        app.client.get("/v1/public/posts", params={"category": "selfie"}), 422, "validation_failed"
    )


def test_guest_listing_is_capped_at_three_pages(app: LiveApp) -> None:  # noqa: F811
    author, _ = _user(app)
    cusco = _destination(app, "peru/cusco")
    for i in range(8):
        _create(
            app,
            author,
            body=f"Cusco tip {i}",
            location_precision="destination",
            destination_id=cusco,
        )
    cursor = None
    pages = 0
    while True:
        params = {"destination_id": cusco, "limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = app.client.get("/v1/public/posts", params=params).json()
        pages += 1
        assert len(body["data"]) == 2
        cursor = body["page"]["next_cursor"]
        if not body["page"]["has_more"]:
            break
    assert pages == 3
