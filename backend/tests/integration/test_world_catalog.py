"""The world gazetteer in the catalog (ADR-0035): loading, search as you type, point resolution.

A small sample in the shape of the seed files is loaded over the launch catalog. Resolution here
uses towns only, so it runs without PostGIS too; the module restores the launch catalog after.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.destinations.world_loader import WorldLoadResult, load_world
from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import _seed, _token, _truncate
from tests.integration.test_identity_flows import _auth

pytestmark = [pytest.mark.integration, pytest.mark.req("LOC-005", "DEST-001", "DEST-003")]

BR = {
    "type": "country",
    "code": "BR",
    "geonames_id": 3469034,
    "name": "Brazil",
    "names": {"pt-BR": "Brasil"},
    "continent": "south_america",
    "lat": -15.78,
    "lng": -47.93,
    "time_zone": "America/Sao_Paulo",
    "population": 212_000_000,
    "launch_path": "brazil",
}
UY = {
    "type": "country",
    "code": "UY",
    "geonames_id": 3439705,
    "name": "Uruguay",
    "names": {"pt-BR": "Uruguai"},
    "continent": "south_america",
    "lat": -34.9,
    "lng": -56.19,
    "time_zone": "America/Montevideo",
    "population": 3_400_000,
    "segment": "uruguay",
}


def _town(
    geonames_id: int,
    name: str,
    lat: float,
    lng: float,
    population: int,
    region: str | None,
    **extra: Any,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "type": "town",
        "code": "BR",
        "geonames_id": geonames_id,
        "name": name,
        "names": {},
        "alt": [],
        "region": region,
        "lat": lat,
        "lng": lng,
        "time_zone": "America/Sao_Paulo",
        "population": population,
    }
    return record | extra


TOWNS = [
    _town(
        3451190,
        "Rio de Janeiro",
        -22.90642,
        -43.18223,
        6_700_000,
        "Rio de Janeiro",
        launch_path="brazil/rio-de-janeiro",
    ),
    _town(
        3448439,
        "São Paulo",
        -23.5475,
        -46.63611,
        12_400_000,
        "São Paulo",
        segment="sao-paulo",
        alt=["Sao Paulo", "SP"],
        names={"de": "São Paulo (Stadt)"},
    ),
    _town(3461786, "Guarulhos", -23.46278, -46.53333, 1_300_000, "São Paulo", segment="guarulhos"),
    _town(3467865, "Campinas", -22.90556, -47.06083, 1_031_554, "São Paulo", segment="campinas"),
    _town(
        6316729,
        "Campinas",
        -27.59444,
        -48.60694,
        20_000,
        "Santa Catarina",
        segment="campinas-santa-catarina",
    ),
    _town(
        3456160,
        "Niterói",
        -22.88333,
        -43.10361,
        480_000,
        "Rio de Janeiro",
        segment="niteroi",
        alt=["Niteroi"],
    ),
    _town(
        3441575,
        "Montevideo",
        -34.90328,
        -56.18816,
        1_300_000,
        "Montevideo",
        segment="montevideo",
        code="UY",
        names={"pt-BR": "Montevidéu"},
        time_zone="America/Montevideo",
    ),
]
ATTRACTIONS = [
    {
        "qid": "Q79961",
        "name": "Christ the Redeemer",
        "names": {"pt-BR": "Cristo Redentor"},
        "category": "attraction",
        "lat": -22.95192,
        "lng": -43.21046,
        "sitelinks": 94,
    },
    {
        "qid": "Q1544545",
        "name": "Ibirapuera Park",
        "names": {"pt-BR": "Parque Ibirapuera"},
        "category": "park",
        "lat": -23.58833,
        "lng": -46.65889,
        "sitelinks": 36,
    },
    # The town itself as a "place": skipped.
    {
        "qid": "Q10",
        "name": "Campinas",
        "names": {},
        "category": "attraction",
        "lat": -22.906,
        "lng": -47.06,
        "sitelinks": 50,
    },
    # Far from every town: skipped.
    {
        "qid": "Q11",
        "name": "Mid-ocean rock",
        "names": {},
        "category": "viewpoint",
        "lat": -30.0,
        "lng": -30.0,
        "sitelinks": 9,
    },
]


def _load(url: str, cities: list[Mapping[str, Any]] | None = None) -> WorldLoadResult:
    async def run() -> WorldLoadResult:
        engine = create_async_engine(url)
        try:
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as session, session.begin():
                return await load_world(
                    session,
                    cities if cities is not None else [BR, UY, *TOWNS],
                    ATTRACTIONS,
                    now=datetime(2026, 11, 13, tzinfo=UTC),
                )
        finally:
            await engine.dispose()

    return asyncio.run(run())


@pytest.fixture(scope="module")
def world(schema_db_url: str) -> Iterator[str]:
    _truncate(schema_db_url)
    _seed(schema_db_url)
    first = _load(schema_db_url)
    assert (first.countries_created, first.countries_updated) == (1, 1)
    assert (first.towns_created, first.towns_updated, first.towns_skipped) == (6, 1, 0)
    assert (first.places_created, first.places_skipped) == (2, 2)
    yield schema_db_url
    _truncate(schema_db_url)  # back to the launch catalog for the other modules
    _seed(schema_db_url)


def _get(
    live: LiveApp, url: str, *, lang: str = "pt-BR", token: str | None = None, **params: Any
) -> Any:
    headers = {"Accept-Language": lang} | (_auth(token) if token else {})
    response = live.client.get(url, params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_loading_is_idempotent_and_keeps_launch_rows_editorial(world: str) -> None:
    again = _load(world)
    assert (again.countries_created, again.towns_created, again.places_created) == (0, 0, 0)
    assert again.towns_updated == 7
    assert again.places_updated == 2
    rio = db_scalar(
        world,
        "SELECT population || '|' || region_name || '|' || geonames_id || '|' || in_directory "
        "FROM destinations WHERE slug = 'rio-de-janeiro-br'",
    )
    assert rio == "6700000|Rio de Janeiro|3451190|true"
    assert (
        db_scalar(world, "SELECT in_directory FROM destinations WHERE slug = 'campinas-br'")
        is False
    )
    assert (
        db_scalar(
            world, "SELECT count(*) FROM destinations WHERE slug = 'campinas-santa-catarina-br'"
        )
        == 1
    )


def test_a_hidden_place_stays_hidden_after_reloading(world: str) -> None:
    db_scalar(
        world,
        "UPDATE places SET status = 'hidden' WHERE provider_place_id = 'Q1544545' RETURNING 1",
    )
    try:
        _load(world)
        assert (
            db_scalar(world, "SELECT status FROM places WHERE provider_place_id = 'Q1544545'")
            == "hidden"
        )
    finally:
        db_scalar(
            world,
            "UPDATE places SET status = 'active' WHERE provider_place_id = 'Q1544545' RETURNING 1",
        )


def test_gazetteer_towns_stay_out_of_the_directory(world: str, live_app: LiveApp) -> None:
    listed = _get(live_app, "/v1/destinations", country="BR", limit=50)
    assert "brazil/sao-paulo" not in {d["path"] for d in listed["data"]}
    brazil = _get(live_app, "/v1/destinations/lookup", path="brazil")
    children = _get(live_app, f"/v1/destinations/{brazil['id']}/children", limit=50)
    assert {d["path"] for d in children["data"]} == {"brazil/rio-de-janeiro"}
    # Still reachable by path, with its region.
    campinas = _get(live_app, "/v1/destinations/lookup", path="brazil/campinas")
    assert_matches_contract(campinas, "Destination")
    assert campinas["region_name"] == "São Paulo"
    assert campinas["country_name"] == "Brasil"


def test_search_finds_towns_by_any_name_with_their_region(world: str, live_app: LiveApp) -> None:
    found = _get(live_app, "/v1/destinations/search", q="campinas")
    assert_matches_contract(found, "DestinationSummaryPage")
    assert [(d["name"], d["region_name"]) for d in found["data"][:2]] == [
        ("Campinas", "São Paulo"),  # the bigger namesake first
        ("Campinas", "Santa Catarina"),
    ]
    assert _get(live_app, "/v1/destinations/search", q="niteroi")["data"][0]["path"] == (
        "brazil/niteroi"
    )
    # Two letters match the start of a name or an abbreviation.
    short = _get(live_app, "/v1/destinations/search", q="SP")
    assert "brazil/sao-paulo" in {d["path"] for d in short["data"]}
    # Localized names of new countries.
    assert _get(live_app, "/v1/destinations/search", q="uruguai")["data"][0]["name"] == "Uruguai"


def test_suggestions_mix_towns_and_tourist_places(world: str, live_app: LiveApp) -> None:
    cristo = _get(live_app, "/v1/destinations/suggest", q="cristo")
    assert_matches_contract(cristo, "SuggestionPage")
    first = cristo["data"][0]
    assert first["type"] == "place"
    assert first["place"]["name"] == "Cristo Redentor"
    assert first["destination"]["path"] == "brazil/rio-de-janeiro"
    town = _get(live_app, "/v1/destinations/suggest", q="sao paulo")["data"][0]
    assert (town["type"], town["destination"]["path"]) == ("destination", "brazil/sao-paulo")
    assert town["place"] is None
    park = _get(live_app, "/v1/destinations/suggest", q="ibirapuera")["data"][0]
    assert park["place"]["name"] == "Parque Ibirapuera"
    assert park["destination"]["path"] == "brazil/sao-paulo"
    english = _get(live_app, "/v1/destinations/suggest", q="christ", lang="en")["data"][0]
    assert english["place"]["name"] == "Christ the Redeemer"


def test_suggestions_validate_their_input(world: str, live_app: LiveApp) -> None:
    assert live_app.client.get("/v1/destinations/suggest", params={"q": "a"}).status_code == 422
    too_many = live_app.client.get("/v1/destinations/suggest", params={"q": "rio", "limit": 50})
    assert too_many.status_code == 422
    nothing = _get(live_app, "/v1/destinations/suggest", q="%_\\")
    assert nothing["data"] == []


def test_points_resolve_to_the_town_they_are_in(world: str, live_app: LiveApp) -> None:
    token = _token(live_app)

    def resolved(near: str, **params: Any) -> str:
        body = _get(live_app, "/v1/destinations/resolve", token=token, near=near, **params)
        assert_matches_contract(body, "Destination")
        return str(body["path"])

    assert resolved("-23.454,-46.533") == "brazil/guarulhos"
    assert resolved("-23.540,-46.456") == "brazil/sao-paulo"  # São Paulo's outskirts
    assert resolved("-22.883,-43.104") == "brazil/niteroi"  # not Rio across the bay
    assert resolved("-34.90,-56.17") == "uruguay/montevideo"
    far = live_app.client.get(
        "/v1/destinations/resolve", params={"near": "-30.0,-30.0"}, headers=_auth(token)
    )
    assert far.status_code == 422
    assert far.json()["code"] == "location_unresolvable"


def test_the_nearby_feed_works_in_any_town(world: str, live_app: LiveApp) -> None:
    token = _token(live_app)
    body = _get(
        live_app, "/v1/feed", token=token, tab="nearby", near="-22.906,-47.061", radius_km=10
    )
    assert body["context"]["source"] == "gps"
    assert body["context"]["destination"]["path"] == "brazil/campinas"
