"""Traveler discovery end to end (BL-2.01..2.03, BL-2.09; DISC-001..008, T-LOC-01..04)."""

from __future__ import annotations

import json
import random
import uuid
from typing import Any

import pytest

from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import _problem, _user, app  # noqa: F401

pytestmark = pytest.mark.integration

FORBIDDEN_KEYS = {
    "lat",
    "lng",
    "latitude",
    "longitude",
    "distance",
    "distance_km",
    "last_seen",
    "point",
}


@pytest.fixture(autouse=True)
def _no_open_sessions(app: LiveApp) -> None:  # noqa: F811
    """Users from earlier tests share this database: close their sessions first."""
    db_scalar(
        app.db_url,
        "WITH closed AS (UPDATE traveler_discovery_sessions SET ended_at = now() "
        "WHERE ended_at IS NULL RETURNING 1) SELECT count(*) FROM closed",
    )


def _destination(live: LiveApp, path: str) -> str:
    return str(live.client.get("/v1/destinations/lookup", params={"path": path}).json()["id"])


def _traveler(
    live: LiveApp,
    *,
    interests: list[str] = (),  # type: ignore[assignment]
    styles: list[str] = (),  # type: ignore[assignment]
    languages: list[str] = ("en",),  # type: ignore[assignment]
    granularity: str = "city",
    opt_in: bool = True,
) -> tuple[str, str]:
    token, user_id = _user(live)
    headers = _auth(token)
    live.client.patch(
        "/v1/users/me",
        headers=headers,
        json={
            "interests": list(interests),
            "travel_styles": list(styles),
            "languages_spoken": list(languages),
            "bio": "Slow traveller who loves markets",
        },
    )
    if opt_in:
        consent = live.client.post(
            "/v1/users/me/consents",
            headers=headers,
            json={
                "consent_type": "traveler_discovery",
                "version": "2026-11-01",
                "granted": True,
                "source": "prompt",
            },
        )
        assert consent.status_code == 201, consent.text
        enabled = live.client.patch(
            "/v1/users/me/privacy",
            headers=headers,
            json={"discovery_enabled": True, "discovery_granularity": granularity},
        )
        assert enabled.status_code == 200, enabled.text
    return token, user_id


def _start(live: LiveApp, token: str, destination: str, **body: Any) -> Any:
    return live.client.put(
        "/v1/users/me/discovery-location",
        headers=_auth(token),
        json={"mode": "destination", "destination_id": destination, **body},
    )


def _discover(live: LiveApp, token: str, **params: Any) -> Any:
    return live.client.get("/v1/travelers/discover", headers=_auth(token), params=params)


def _ids(response: Any) -> list[str]:
    assert response.status_code == 200, response.text
    assert_matches_contract(response.json(), "TravelerCardPage")
    return [card["user"]["id"] for card in response.json()["data"]]


def _keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


@pytest.mark.req("DISC-001", "DISC-002", "DISC-003")
def test_sessions_need_opt_in_and_hold_only_destinations(app: LiveApp) -> None:  # noqa: F811
    lisbon = _destination(app, "portugal/lisbon")
    outsider, _ = _traveler(app, opt_in=False)
    _problem(_start(app, outsider, lisbon), 403, "consent_required")

    token, user_id = _traveler(app)
    started = _start(
        app,
        token,
        lisbon,
        duration_hours=6,
        travel_start_date="2026-12-01",
        travel_end_date="2026-12-05",
    )
    assert started.status_code == 200, started.text
    body = started.json()
    assert_matches_contract(body, "DiscoverySession")
    assert (body["destination"]["id"], body["area"], body["source"], body["visibility"]) == (
        lisbon,
        None,
        "manual",
        "visible",
    )
    assert not _keys(body) & FORBIDDEN_KEYS
    current = app.client.get("/v1/users/me/discovery-location", headers=_auth(token))
    assert current.json()["id"] == body["id"]
    columns = db_scalar(
        app.db_url,
        "SELECT string_agg(column_name, ',') FROM information_schema.columns "
        "WHERE table_name = 'traveler_discovery_sessions'",
    )
    assert not {"lat", "lng", "point", "location", "geom"} & set(str(columns).split(","))

    assert (
        app.client.delete("/v1/users/me/discovery-location", headers=_auth(token)).status_code
        == 204
    )
    assert (
        app.client.delete("/v1/users/me/discovery-location", headers=_auth(token)).status_code
        == 204
    )
    _problem(
        app.client.get("/v1/users/me/discovery-location", headers=_auth(token)), 404, "not_found"
    )
    _problem(_start(app, token, lisbon, duration_hours=73), 422, "validation_failed")
    _problem(
        _start(app, token, lisbon, travel_start_date="2026-12-05", travel_end_date="2026-12-01"),
        422,
        "validation_failed",
    )
    assert user_id


@pytest.mark.req("DISC-003", "PROF-007")
def test_neighbourhood_presence_only_when_chosen(app: LiveApp) -> None:  # noqa: F811
    lisbon, alfama = (
        _destination(app, "portugal/lisbon"),
        _destination(app, "portugal/lisbon/alfama"),
    )
    city_level, _ = _traveler(app)
    body = _start(app, city_level, alfama).json()
    assert (body["destination"]["id"], body["area"], body["granularity"]) == (lisbon, None, "city")
    precise, _ = _traveler(app, granularity="neighborhood")
    body = _start(app, precise, alfama).json()
    assert (body["destination"]["id"], body["area"]["id"], body["granularity"]) == (
        lisbon,
        alfama,
        "neighborhood",
    )
    _problem(
        _start(
            app,
            precise,
            lisbon,
            area_destination_id=_destination(app, "brazil/rio-de-janeiro/ipanema"),
        ),
        422,
        "validation_failed",
    )


@pytest.mark.req("DISC-002", "DISC-009")
@pytest.mark.security
def test_sessions_expire_and_destination_switches_are_limited(app: LiveApp) -> None:  # noqa: F811
    lisbon = _destination(app, "portugal/lisbon")
    token, user_id = _traveler(app)
    viewer, _ = _traveler(app)
    _start(app, token, lisbon)
    _start(app, viewer, lisbon)
    assert user_id in _ids(_discover(app, viewer))
    db_scalar(
        app.db_url,
        "UPDATE traveler_discovery_sessions SET expires_at = now() - interval '1 second' "
        "WHERE user_id = :u RETURNING 1",
        u=uuid.UUID(user_id),
    )
    assert user_id not in _ids(_discover(app, viewer))  # gone immediately, no job needed
    _problem(
        app.client.get("/v1/users/me/discovery-location", headers=_auth(token)), 404, "not_found"
    )
    for _ in range(9):
        assert _start(app, token, lisbon).status_code == 200
    _problem(_start(app, token, lisbon), 429, "rate_limited")


@pytest.mark.req("DISC-004", "DISC-005", "DISC-006", "DISC-007", "DISC-008")
@pytest.mark.security
def test_discover_is_reciprocal_safe_and_coarse(app: LiveApp) -> None:  # noqa: F811
    lisbon, rio = _destination(app, "portugal/lisbon"), _destination(app, "brazil/rio-de-janeiro")
    viewer, viewer_id = _traveler(app, interests=["food", "art"], styles=["backpacking"])
    twin, twin_id = _traveler(app, interests=["food", "art"], styles=["backpacking"])
    stranger, stranger_id = _traveler(app, interests=["golf"], languages=["de"])
    hidden, hidden_id = _traveler(app)
    blocked, blocked_id = _traveler(app)
    private, private_id = _traveler(app, interests=["food"])
    app.client.patch("/v1/users/me", headers=_auth(private), json={"account_visibility": "private"})
    elsewhere, elsewhere_id = _traveler(app)
    for token in (viewer, twin, stranger, blocked, private):
        assert _start(app, token, lisbon).status_code == 200
    _start(app, hidden, lisbon, visibility="invisible")
    _start(app, elsewhere, rio)
    app.client.put(f"/v1/users/{viewer_id}/block", headers=_auth(blocked))

    response = _discover(app, viewer, **{"language": "en"})
    found = _ids(response)
    assert set(found) == {twin_id, private_id}  # stranger filtered by language
    everyone = _ids(_discover(app, viewer))
    assert set(everyone) == {twin_id, stranger_id, private_id}
    for absent in (hidden_id, blocked_id, elsewhere_id):
        assert absent not in everyone
    assert not _keys(response.json()) & FORBIDDEN_KEYS
    cards = {c["user"]["id"]: c for c in response.json()["data"]}
    assert cards[twin_id]["compatibility"] == "high"
    assert cards[twin_id]["shared"] == {
        "travel_styles": ["backpacking"],
        "interests": ["art", "food"],
        "languages": ["en"],
    }
    assert cards[twin_id]["presence"]["destination"]["id"] == lisbon
    assert cards[twin_id]["presence"]["area"] is None
    assert cards[twin_id]["bio_snippet"] == "Slow traveller who loves markets"
    assert cards[twin_id]["can_request_connection"] is True
    assert cards[private_id]["bio_snippet"] is None  # profile visibility respected
    assert cards[private_id]["interests"] == []

    # Invisible users neither appear nor browse; nobody browses another city.
    _problem(_discover(app, hidden), 403, "discovery_disabled")
    _problem(_discover(app, viewer, destination_id=rio), 403, "discovery_disabled")
    # Opting out removes you at once, even with a session still open.
    app.client.patch("/v1/users/me/privacy", headers=_auth(twin), json={"discovery_enabled": False})
    assert twin_id not in _ids(_discover(app, viewer))
    _problem(_discover(app, twin), 403, "discovery_disabled")


@pytest.mark.req("DISC-008", "CONN-004")
def test_declined_requesters_go_last_and_discovery_is_shared_context(app: LiveApp) -> None:  # noqa: F811
    lisbon = _destination(app, "portugal/lisbon")
    viewer, viewer_id = _traveler(app, interests=["food"])
    pushy, pushy_id = _traveler(app, interests=["food"])
    others = [_traveler(app, interests=["food"])[1] for _ in range(3)]
    shy, shy_id = _traveler(app)
    app.client.patch(
        "/v1/users/me/privacy",
        headers=_auth(shy),
        json={"connection_requests_from": "shared_context"},
    )
    for token in (viewer, pushy, shy):
        _start(app, token, lisbon)
    for user_id in others:
        db_scalar(
            app.db_url,
            "INSERT INTO traveler_discovery_sessions "
            "(id, user_id, destination_id, source, visibility, expires_at) VALUES "
            "(gen_random_uuid(), :u, :d, 'manual', 'visible', now() + interval '1 day') "
            "RETURNING 1",
            u=uuid.UUID(user_id),
            d=uuid.UUID(lisbon),
        )
    request = app.client.post(
        "/v1/connections/requests",
        headers={**_auth(pushy), "Idempotency-Key": str(uuid.uuid4())},
        json={"recipient_id": viewer_id, "context": "discovery"},
    ).json()
    app.client.post(f"/v1/connections/requests/{request['id']}/decline", headers=_auth(viewer))
    app.client.app.state.discovery_service._rng = random.Random(3)  # type: ignore[attr-defined]  # noqa: S311
    order = _ids(_discover(app, viewer))
    assert order[-1] == pushy_id  # declined requesters come after everyone else
    assert set(order) == {pushy_id, shy_id, *others}
    # Discovering the same city counts as shared context for connection requests.
    sent = app.client.post(
        "/v1/connections/requests",
        headers={**_auth(viewer), "Idempotency-Key": str(uuid.uuid4())},
        json={"recipient_id": shy_id, "context": "discovery"},
    )
    assert sent.status_code == 201, sent.text


@pytest.mark.req("LOC-004", "DISC-005")
def test_upcoming_scope_matches_shared_overlapping_trips(app: LiveApp) -> None:  # noqa: F811
    lisbon = _destination(app, "portugal/lisbon")

    def plan(token: str, start: str, end: str, share: bool = True) -> None:
        response = app.client.post(
            "/v1/users/me/upcoming-destinations",
            headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())},
            json={
                "destination_id": lisbon,
                "start_date": start,
                "end_date": end,
                "share_for_discovery": share,
            },
        )
        assert response.status_code == 201, response.text

    viewer, _ = _traveler(app)
    overlapping, overlapping_id = _traveler(app)
    later, later_id = _traveler(app)
    private_trip, private_trip_id = _traveler(app)
    _problem(
        _discover(app, viewer, scope="upcoming", destination_id=lisbon), 403, "discovery_disabled"
    )
    plan(viewer, "2026-12-01", "2026-12-10")
    plan(overlapping, "2026-12-08", "2026-12-15")
    plan(later, "2027-02-01", "2027-02-05")
    plan(private_trip, "2026-12-02", "2026-12-04", share=False)
    found = _ids(_discover(app, viewer, scope="upcoming", destination_id=lisbon))
    assert found == [overlapping_id]
    card = _discover(app, viewer, scope="upcoming", destination_id=lisbon).json()["data"][0]
    assert card["presence"]["kind"] == "upcoming"
    assert card["presence"]["travel_start_date"] == "2026-12-08"
    assert later_id not in found
    assert private_trip_id not in found


@pytest.mark.req("DISC-003", "LOC-009")
@pytest.mark.security
def test_gps_points_are_resolved_and_discarded(app: LiveApp) -> None:  # noqa: F811
    if not db_scalar(app.db_url, "SELECT to_regclass('destination_boundaries') IS NOT NULL"):
        pytest.skip("PostGIS not installed on this PostgreSQL (runs in CI)")
    token, _ = _traveler(app, granularity="neighborhood")
    response = app.client.put(
        "/v1/users/me/discovery-location",
        headers=_auth(token),
        json={"mode": "gps", "point": {"lat": -22.9711, "lng": -43.1822, "accuracy_m": 30}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "gps_resolved"
    assert body["destination"]["path"] == "brazil/rio-de-janeiro"
    assert "-22.97" not in json.dumps(body)
    assert "-43.18" not in json.dumps(body)
    nowhere = app.client.put(
        "/v1/users/me/discovery-location",
        headers=_auth(token),
        json={"mode": "gps", "point": {"lat": 0.0, "lng": -160.0}},
    )
    _problem(nowhere, 422, "location_unresolvable")
