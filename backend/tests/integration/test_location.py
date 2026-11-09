"""Browse and upcoming destinations against PostgreSQL (BL-1.07, LOC-002)."""

from __future__ import annotations

from typing import Any

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import TERMS, _auth, _id_token, _register

pytestmark = pytest.mark.integration


def _user(live: LiveApp, locale: str = "en") -> str:
    response = _register(live, _id_token(live), locale=locale)
    assert response.status_code == 201, response.text
    return str(response.json()["tokens"]["access_token"])


def _destination_id(live: LiveApp, path: str) -> str:
    response = live.client.get("/v1/destinations/lookup", params={"path": path})
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _problem(response: Any, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["code"] == code


# ─────────────────────────────── browse ───────────────────────────────


@pytest.mark.req("LOC-002")
def test_browse_destination_round_trip(catalog: str, live_app: LiveApp) -> None:  # noqa: F811
    token = _user(live_app, locale="de")
    assert (
        live_app.client.get("/v1/users/me", headers=_auth(token)).json()["browse_destination"]
        is None
    )
    _problem(
        live_app.client.get("/v1/users/me/browse-destination", headers=_auth(token)),
        404,
        "not_found",
    )

    lisbon = _destination_id(live_app, "portugal/lisbon")
    put = live_app.client.put(
        "/v1/users/me/browse-destination",
        headers={**_auth(token), "Accept-Language": "de"},
        json={"destination_id": lisbon},
    )
    assert put.status_code == 200, put.text
    assert_matches_contract(put.json(), "BrowseDestination")
    assert put.json()["destination"]["name"] == "Lissabon"

    me = live_app.client.get("/v1/users/me", headers=_auth(token)).json()
    assert_matches_contract(me, "Me")
    # Localized in the user's UI language (registered with locale de).
    assert me["browse_destination"]["name"] == "Lissabon"

    rio = _destination_id(live_app, "brazil/rio-de-janeiro")
    live_app.client.put(
        "/v1/users/me/browse-destination", headers=_auth(token), json={"destination_id": rio}
    )
    current = live_app.client.get("/v1/users/me/browse-destination", headers=_auth(token))
    assert current.json()["destination"]["path"] == "brazil/rio-de-janeiro"
    assert (
        db_scalar(catalog, "SELECT count(*) FROM user_selected_locations WHERE kind = 'browse'")
        == 1
    )

    cleared = live_app.client.delete("/v1/users/me/browse-destination", headers=_auth(token))
    assert cleared.status_code == 204
    _problem(
        live_app.client.get("/v1/users/me/browse-destination", headers=_auth(token)),
        404,
        "not_found",
    )


def test_browse_requires_an_active_destination(catalog: str, live_app: LiveApp) -> None:  # noqa: F811
    token = _user(live_app)
    unknown = live_app.client.put(
        "/v1/users/me/browse-destination",
        headers=_auth(token),
        json={"destination_id": "0190f5c2-0000-7000-8000-000000000001"},
    )
    _problem(unknown, 404, "not_found")
    alfama = _destination_id(live_app, "portugal/lisbon/alfama")
    live_app.client.put(
        "/v1/users/me/browse-destination", headers=_auth(token), json={"destination_id": alfama}
    )
    db_scalar(
        catalog, "UPDATE destinations SET status = 'hidden' WHERE id = :i RETURNING 1", i=alfama
    )
    try:
        hidden = live_app.client.get("/v1/users/me/browse-destination", headers=_auth(token))
        _problem(hidden, 404, "not_found")
        me = live_app.client.get("/v1/users/me", headers=_auth(token)).json()
        assert me["browse_destination"] is None
    finally:
        db_scalar(
            catalog, "UPDATE destinations SET status = 'active' WHERE id = :i RETURNING 1", i=alfama
        )


def test_location_endpoints_require_authentication(catalog: str, live_app: LiveApp) -> None:  # noqa: F811
    assert live_app.client.get("/v1/users/me/browse-destination").status_code == 401
    assert live_app.client.get("/v1/users/me/upcoming-destinations").status_code == 401


# ─────────────────────────────── upcoming ───────────────────────────────


def _add(live: LiveApp, token: str, **body: Any) -> Any:
    return live.client.post("/v1/users/me/upcoming-destinations", headers=_auth(token), json=body)


@pytest.mark.req("LOC-005", "FEED-001")
def test_upcoming_destinations(catalog: str, live_app: LiveApp) -> None:  # noqa: F811
    token = _user(live_app)
    tokyo = _destination_id(live_app, "japan/tokyo")
    paris = _destination_id(live_app, "france/paris")
    later = _add(
        live_app, token, destination_id=tokyo, start_date="2027-04-01", end_date="2027-04-10"
    )
    assert later.status_code == 201, later.text
    assert_matches_contract(later.json(), "UpcomingDestination")
    sooner = _add(live_app, token, destination_id=paris, start_date="2027-01-05")
    assert sooner.status_code == 201

    listing = live_app.client.get("/v1/users/me/upcoming-destinations", headers=_auth(token))
    assert listing.status_code == 200
    paths = [u["destination"]["path"] for u in listing.json()["data"]]
    assert paths == ["france/paris", "japan/tokyo"]  # soonest first
    for item in listing.json()["data"]:
        assert_matches_contract(item, "UpcomingDestination")

    _problem(_add(live_app, token, destination_id=tokyo), 409, "conflict")
    removed = live_app.client.delete(
        f"/v1/users/me/upcoming-destinations/{later.json()['id']}", headers=_auth(token)
    )
    assert removed.status_code == 204
    again = live_app.client.delete(
        f"/v1/users/me/upcoming-destinations/{later.json()['id']}", headers=_auth(token)
    )
    _problem(again, 404, "not_found")


def test_upcoming_validation(catalog: str, live_app: LiveApp) -> None:  # noqa: F811
    token = _user(live_app)
    rome = _destination_id(live_app, "italy/rome")
    _problem(
        _add(live_app, token, destination_id=rome, start_date="2027-05-10", end_date="2027-05-01"),
        422,
        "validation_failed",
    )
    _problem(
        _add(live_app, token, destination_id="0190f5c2-0000-7000-8000-000000000001"),
        404,
        "not_found",
    )


@pytest.mark.req("DISC-001")
@pytest.mark.security
def test_sharing_upcoming_trips_requires_discovery_consent(catalog: str, live_app: LiveApp) -> None:  # noqa: F811
    token = _user(live_app)
    cusco = _destination_id(live_app, "peru/cusco")
    denied = _add(live_app, token, destination_id=cusco, share_for_discovery=True)
    _problem(denied, 403, "consent_required")
    live_app.client.post(
        "/v1/users/me/consents",
        headers=_auth(token),
        json={
            "consent_type": "traveler_discovery",
            "version": TERMS,
            "granted": True,
            "source": "prompt",
        },
    )
    allowed = _add(live_app, token, destination_id=cusco, share_for_discovery=True)
    assert allowed.status_code == 201, allowed.text
    assert allowed.json()["share_for_discovery"] is True


@pytest.mark.security
def test_users_cannot_remove_each_others_selections(catalog: str, live_app: LiveApp) -> None:  # noqa: F811
    owner, other = _user(live_app), _user(live_app)
    sydney = _destination_id(live_app, "australia/sydney")
    created = _add(live_app, owner, destination_id=sydney)
    response = live_app.client.delete(
        f"/v1/users/me/upcoming-destinations/{created.json()['id']}", headers=_auth(other)
    )
    _problem(response, 404, "not_found")
