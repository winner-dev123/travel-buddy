"""Saved places (BL-4.04; TRIP-003): idempotent saves into collections, filters, paging."""

from __future__ import annotations

import uuid

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_places import (  # noqa: F401 - autouse catalog cleanup
    _document,
    _fresh_catalog,
    _ingest,
    _place_id,
)
from tests.integration.test_posts import _destination, _problem, _user, app  # noqa: F401

pytestmark = pytest.mark.integration

BASE = "/v1/users/me/saved-places"


@pytest.mark.req("TRIP-003")
def test_save_list_filter_and_unsave_places(app: LiveApp) -> None:  # noqa: F811
    _ingest(app, _document())
    token, _ = _user(app)
    headers = {**_auth(token), "Accept-Language": "en"}
    tower, market = _place_id(app, "belem-tower"), _place_id(app, "time-out-market")

    saved = app.client.put(f"{BASE}/{tower}", headers=headers)  # no body: default collection
    assert saved.status_code == 200, saved.text
    assert_matches_contract(saved.json(), "SavedPlace")
    assert saved.json()["place"]["name"] == "Belém Tower"
    assert saved.json()["collection"] == "default"
    again = app.client.put(f"{BASE}/{tower}", headers=headers, json={"note": "At sunset"})
    assert again.json()["note"] == "At sunset"  # idempotent: same save, updated note
    assert again.json()["created_at"] == saved.json()["created_at"]
    app.client.put(f"{BASE}/{market}", headers=headers, json={"collection": "food"})
    app.client.put(f"{BASE}/{tower}", headers=headers, json={"collection": "food"})

    listed = app.client.get(BASE, headers=headers)
    assert listed.status_code == 200, listed.text
    assert_matches_contract(listed.json(), "SavedPlacePage")
    assert len(listed.json()["data"]) == 3
    food = app.client.get(BASE, headers=headers, params={"collection": "food"}).json()
    assert {s["place"]["name"] for s in food["data"]} == {"Belém Tower", "Time Out Market"}
    in_lisbon = app.client.get(
        BASE, headers=headers, params={"destination_id": _destination(app, "portugal/lisbon")}
    ).json()
    assert len(in_lisbon["data"]) == 3
    in_brazil = app.client.get(
        BASE, headers=headers, params={"destination_id": _destination(app, "brazil")}
    ).json()
    assert in_brazil["data"] == []

    first = app.client.get(BASE, headers=headers, params={"limit": 2}).json()
    assert len(first["data"]) == 2
    rest = app.client.get(
        BASE, headers=headers, params={"limit": 2, "cursor": first["page"]["next_cursor"]}
    ).json()
    assert len(rest["data"]) == 1
    assert rest["page"]["next_cursor"] is None
    seen = [(s["place"]["id"], s["collection"]) for s in first["data"] + rest["data"]]
    assert len(set(seen)) == 3
    _problem(
        app.client.get(
            BASE,
            headers=headers,
            params={"collection": "food", "cursor": first["page"]["next_cursor"]},
        ),
        400,
        "invalid_cursor",
    )

    removed = app.client.delete(f"{BASE}/{tower}", headers=headers, params={"collection": "food"})
    assert removed.status_code == 204
    assert app.client.delete(f"{BASE}/{tower}", headers=headers, params={"collection": "food"})
    food = app.client.get(BASE, headers=headers, params={"collection": "food"}).json()
    assert [s["place"]["name"] for s in food["data"]] == ["Time Out Market"]

    # A place taken down from the catalog drops out of the list; another user sees nothing.
    db_scalar(
        app.db_url,
        "UPDATE places SET status = 'hidden' WHERE provider_place_id = 'time-out-market' "
        "RETURNING 1",
    )
    names = [s["place"]["name"] for s in app.client.get(BASE, headers=headers).json()["data"]]
    assert names == ["Belém Tower"]
    other, _ = _user(app)
    assert app.client.get(BASE, headers=_auth(other)).json()["data"] == []


@pytest.mark.req("TRIP-003")
def test_only_listed_places_can_be_saved(app: LiveApp) -> None:  # noqa: F811
    _ingest(app, _document())
    token, _ = _user(app)
    _problem(app.client.put(f"{BASE}/{uuid.uuid4()}", headers=_auth(token)), 404, "not_found")
    _problem(
        app.client.put(
            f"{BASE}/{_place_id(app, 'belem-tower')}",
            headers=_auth(token),
            json={"collection": ""},
        ),
        422,
        "validation_failed",
    )
    assert app.client.get(BASE).status_code == 401
