"""``GET /v1/users/me/approximate-location`` (LOC-004, LOC-010, ADR-0030)."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import pytest

from app.modules.location.ip_geolocation import IpLocation
from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import _problem, _user, app  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.req("LOC-010")]

PATH = "/v1/users/me/approximate-location"


class _Geolocator:
    """Stands in for the database; remembers which addresses it was asked about."""

    def __init__(self) -> None:
        self.answer: IpLocation | None = None
        self.asked: list[str] = []

    def locate(self, address: str) -> IpLocation | None:
        self.asked.append(address)
        return self.answer


@pytest.fixture
def geolocator(app: LiveApp) -> Iterator[_Geolocator]:  # noqa: F811
    service = app.client.app.state.approximate_location_service  # type: ignore[attr-defined]
    original = service._geolocator
    fake = _Geolocator()
    service._geolocator = fake
    yield fake
    service._geolocator = original


def _point(lat: float, lng: float, city: str | None, code: str | None) -> IpLocation:
    names = {"en": "Finland", "de": "Finnland"} if code == "FI" else {}
    return IpLocation(lat=lat, lng=lng, city=city, country_code=code, country_names=names)


def test_an_uncovered_area_is_named_but_offers_no_city(
    app: LiveApp,  # noqa: F811
    geolocator: _Geolocator,
) -> None:
    token, _ = _user(app)
    # Far from every town and outside every boundary (ADR-0035 resolves anything near a town).
    geolocator.answer = _point(-77.84633, 166.67628, "McMurdo Station", None)
    response = app.client.get(PATH, headers={**_auth(token), "Accept-Language": "de"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert_matches_contract(body, "ApproximateLocation")
    assert body["source"] == "ip"
    assert body["precision"] == "city"
    assert body["destination"] is None
    assert body["label"] == "McMurdo Station"
    # Rounded to 0.01° (about 1 km): never finer than a city.
    assert body["center"] == {"lat": -77.85, "lng": 166.68}
    assert geolocator.asked  # the request's client address was looked up


def test_a_country_only_answer_is_country_precision(
    app: LiveApp,  # noqa: F811
    geolocator: _Geolocator,
) -> None:
    token, _ = _user(app)
    # With PostGIS this point lies in Finland: a country alone is still no city to share.
    geolocator.answer = _point(64.5, 26.0, None, "FI")
    response = app.client.get(PATH, headers={**_auth(token), "Accept-Language": "de"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["precision"] == "country"
    assert body["label"] == "Finnland"
    assert body["destination"] is None


@pytest.mark.req("LOC-004")
def test_an_unknown_address_asks_for_a_city(
    app: LiveApp,  # noqa: F811
    geolocator: _Geolocator,
) -> None:
    token, _ = _user(app)
    geolocator.answer = None
    _problem(app.client.get(PATH, headers=_auth(token)), 422, "location_unresolvable")
    # Looking it up changes nothing: no discovery session appears.
    session = app.client.get("/v1/users/me/discovery-location", headers=_auth(token))
    assert session.status_code == 404


def test_signing_in_is_required(app: LiveApp, geolocator: _Geolocator) -> None:  # noqa: F811
    assert app.client.get(PATH).status_code == 401
    assert geolocator.asked == []


@pytest.mark.security
@pytest.mark.req("LOC-009")
def test_a_covered_city_comes_back_with_its_public_centre(
    app: LiveApp,  # noqa: F811
    geolocator: _Geolocator,
    caplog: pytest.LogCaptureFixture,
) -> None:
    if not db_scalar(app.db_url, "SELECT to_regclass('destination_boundaries') IS NOT NULL"):
        pytest.skip("PostGIS not installed on this PostgreSQL (runs in CI)")
    token, _ = _user(app)
    # A point inside Alfama: an address never places anyone in a neighbourhood, only its city.
    geolocator.answer = _point(38.711383, -9.130117, "Lisbon", "PT")
    with caplog.at_level(logging.DEBUG):
        response = app.client.get(PATH, headers=_auth(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert_matches_contract(body, "ApproximateLocation")
    assert body["destination"]["path"] == "portugal/lisbon"
    assert body["center"] == body["destination"]["centroid"]
    assert body["label"] == "Lisbon, Portugal"
    text = json.dumps(body)
    assert "38.7113" not in text
    assert "-9.1301" not in text
    assert "38.7113" not in caplog.text
    assert "-9.1301" not in caplog.text
    # Helsinki is a launch city too.
    geolocator.answer = _point(60.1699, 24.9384, "Helsinki", "FI")
    helsinki = app.client.get(PATH, headers=_auth(token)).json()
    assert helsinki["destination"]["path"] == "finland/helsinki"
