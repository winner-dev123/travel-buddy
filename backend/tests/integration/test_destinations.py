"""Destinations against PostgreSQL with the launch catalog loaded (BL-1.05).

Point resolution needs PostGIS (CI); those tests skip on databases without it.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.destinations.seeding import SeedResult, load_catalog, read_document
from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_identity_flows import _auth, _id_token, _register

pytestmark = pytest.mark.integration


def _seed(url: str) -> SeedResult:
    async def run() -> SeedResult:
        engine = create_async_engine(url)
        try:
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as session, session.begin():
                return await load_catalog(session, read_document())
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _truncate(url: str) -> None:
    async def run() -> None:
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text("TRUNCATE destinations CASCADE"))
        finally:
            await engine.dispose()

    asyncio.run(run())


@pytest.fixture(scope="module")
def catalog(schema_db_url: str) -> str:
    _truncate(schema_db_url)
    result = _seed(schema_db_url)
    assert result.created == 41
    return schema_db_url


def _get(live: LiveApp, url: str, /, *, lang: str | None = None, **params: Any) -> Any:
    headers = {"Accept-Language": lang} if lang else {}
    return live.client.get(url, params=params, headers=headers)


def _ok(response: Any, schema: str) -> Any:
    assert response.status_code == 200, response.text
    body = response.json()
    assert_matches_contract(body, schema)
    return body


# ─────────────────────────────── directory ───────────────────────────────


@pytest.mark.req("DEST-006")
def test_slug_sort_enumerates_every_destination_exactly_once(
    catalog: str, live_app: LiveApp
) -> None:
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        params: dict[str, Any] = {"sort": "slug", "limit": 7}
        if cursor:
            params["cursor"] = cursor
        body = _ok(_get(live_app, "/v1/destinations", **params), "DestinationSummaryPage")
        seen += [d["slug"] for d in body["data"]]
        cursor = body["page"]["next_cursor"]
        if not body["page"]["has_more"]:
            break
    assert len(seen) == len(set(seen)) == 41
    assert seen == sorted(seen)


@pytest.mark.req("DEST-006", "LOC-006")
def test_directory_filters(catalog: str, live_app: LiveApp) -> None:
    europe = _ok(
        _get(live_app, "/v1/destinations", kind="city", continent="europe", limit=50),
        "DestinationSummaryPage",
    )
    assert {d["path"] for d in europe["data"]} == {
        "portugal/lisbon",
        "spain/barcelona",
        "france/paris",
        "italy/rome",
        "iceland/reykjavik",
        "germany/berlin",
        "united-kingdom/london",
    }
    brazil = _ok(
        _get(live_app, "/v1/destinations", country="BR", limit=50), "DestinationSummaryPage"
    )
    assert len(brazil["data"]) == 5  # country, Rio and three neighborhoods
    featured = _ok(_get(live_app, "/v1/destinations/featured"), "DestinationSummaryPage")
    assert "brazil/rio-de-janeiro" in {d["path"] for d in featured["data"]}
    assert all(d["kind"] == "city" for d in featured["data"])


def test_popularity_pages_are_stable(catalog: str, live_app: LiveApp) -> None:
    first = _ok(_get(live_app, "/v1/destinations", limit=4), "DestinationSummaryPage")
    second = _ok(
        _get(live_app, "/v1/destinations", limit=4, cursor=first["page"]["next_cursor"]),
        "DestinationSummaryPage",
    )
    assert not {d["id"] for d in first["data"]} & {d["id"] for d in second["data"]}


def test_cursor_cannot_be_reused_with_other_filters(catalog: str, live_app: LiveApp) -> None:
    first = _ok(_get(live_app, "/v1/destinations", limit=2, country="BR"), "DestinationSummaryPage")
    response = _get(live_app, "/v1/destinations", limit=2, cursor=first["page"]["next_cursor"])
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_cursor"


@pytest.mark.parametrize(
    "params",
    [{"kind": "planet"}, {"continent": "atlantis"}, {"country": "br"}, {"limit": 0}],
)
def test_invalid_directory_parameters(
    catalog: str, live_app: LiveApp, params: dict[str, Any]
) -> None:
    response = _get(live_app, "/v1/destinations", **params)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "validation_failed"


# ─────────────────────────────── localization ───────────────────────────────


@pytest.mark.req("DEST-002", "I18N-002")
@pytest.mark.parametrize(
    ("lang", "name", "country"),
    [("de", "Lissabon", "Portugal"), ("pt-BR", "Lisboa", "Portugal"), ("ja", "Lisbon", "Portugal")],
)
def test_names_follow_accept_language(
    catalog: str, live_app: LiveApp, lang: str, name: str, country: str
) -> None:
    body = _ok(
        _get(live_app, "/v1/destinations/lookup", lang=lang, path="portugal/lisbon"), "Destination"
    )
    assert body["name"] == name
    assert body["country_name"] == country
    assert body["tagline"]


def test_country_names_are_localized_in_summaries(catalog: str, live_app: LiveApp) -> None:
    body = _ok(
        _get(live_app, "/v1/destinations/lookup", lang="fr", path="japan/tokyo"), "Destination"
    )
    assert body["country_name"] == "Japon"
    assert body["ancestors"][0]["name"] == "Japon"


# ─────────────────────────────── search ───────────────────────────────


@pytest.mark.req("DEST-001")
@pytest.mark.parametrize(
    ("q", "expected_path"),
    [
        ("rio de janero", "brazil/rio-de-janeiro"),
        ("lisboa", "portugal/lisbon"),
        ("LISSABON", "portugal/lisbon"),
        ("cuzco", "peru/cusco"),
        ("Reykjavik", "iceland/reykjavik"),
        ("ciudad de mexico", "mexico/mexico-city"),
        ("copa", "brazil/rio-de-janeiro/copacabana"),
    ],
)
def test_search_is_accent_case_and_typo_tolerant(
    catalog: str, live_app: LiveApp, q: str, expected_path: str
) -> None:
    body = _ok(_get(live_app, "/v1/destinations/search", q=q), "DestinationSummaryPage")
    top3 = [d["path"] for d in body["data"][:3]]
    assert expected_path in top3, (q, top3)
    assert body["page"]["next_cursor"] is None


def test_search_filters_by_kind(catalog: str, live_app: LiveApp) -> None:
    body = _ok(
        _get(live_app, "/v1/destinations/search", q="mexico", kind="country"),
        "DestinationSummaryPage",
    )
    assert [d["path"] for d in body["data"]] == ["mexico"]


def test_search_requires_two_characters(catalog: str, live_app: LiveApp) -> None:
    assert _get(live_app, "/v1/destinations/search", q="r").status_code == 422


# ─────────────────────────────── single destination ───────────────────────────────


@pytest.mark.req("LOC-006")
def test_lookup_returns_the_chain(catalog: str, live_app: LiveApp) -> None:
    body = _ok(
        _get(live_app, "/v1/destinations/lookup", path="brazil/rio-de-janeiro/copacabana"),
        "Destination",
    )
    assert body["slug"] == "copacabana-rio-de-janeiro-br"
    assert body["path"] == "brazil/rio-de-janeiro/copacabana"
    assert [a["path"] for a in body["ancestors"]] == ["brazil", "brazil/rio-de-janeiro"]
    assert body["has_children"] is False
    assert body["time_zone"] == "America/Sao_Paulo"
    assert -23 < body["centroid"]["lat"] < -22.9

    by_id = _ok(_get(live_app, f"/v1/destinations/{body['parent_id']}"), "Destination")
    assert by_id["path"] == "brazil/rio-de-janeiro"
    assert by_id["has_children"] is True
    assert by_id["is_featured"] is True


def test_children_lists_neighborhoods(catalog: str, live_app: LiveApp) -> None:
    rio = _ok(
        _get(live_app, "/v1/destinations/lookup", path="brazil/rio-de-janeiro"), "Destination"
    )
    children = _ok(
        _get(live_app, f"/v1/destinations/{rio['id']}/children"), "DestinationSummaryPage"
    )
    assert {c["path"] for c in children["data"]} == {
        "brazil/rio-de-janeiro/copacabana",
        "brazil/rio-de-janeiro/ipanema",
        "brazil/rio-de-janeiro/santa-teresa",
    }


@pytest.mark.parametrize(
    "path",
    [
        "/v1/destinations/lookup?path=brazil/sao-paulo",
        f"/v1/destinations/{'0' * 8}-0000-7000-8000-{'0' * 12}",
    ],
)
def test_unknown_destinations_are_404(catalog: str, live_app: LiveApp, path: str) -> None:
    response = live_app.client.get(path)
    assert response.status_code == 404
    assert_matches_contract(response.json(), "Problem")


def test_hidden_destinations_are_invisible(catalog: str, live_app: LiveApp) -> None:
    db_scalar(
        catalog,
        "UPDATE destinations SET status = 'hidden' WHERE slug = 'alfama-lisbon-pt' RETURNING 1",
    )
    try:
        assert (
            _get(live_app, "/v1/destinations/lookup", path="portugal/lisbon/alfama").status_code
            == 404
        )
        listing = _ok(
            _get(live_app, "/v1/destinations", country="PT", limit=50), "DestinationSummaryPage"
        )
        assert "portugal/lisbon/alfama" not in {d["path"] for d in listing["data"]}
    finally:
        db_scalar(
            catalog,
            "UPDATE destinations SET status = 'active' WHERE slug = 'alfama-lisbon-pt' RETURNING 1",
        )


def test_seeding_is_idempotent(catalog: str) -> None:
    again = _seed(catalog)
    assert (again.created, again.updated) == (0, 41)
    assert db_scalar(catalog, "SELECT count(*) FROM destinations") == 41


# ─────────────────────────────── point resolution (PostGIS) ───────────────────────────────


def _postgis(url: str) -> bool:
    return bool(db_scalar(url, "SELECT to_regclass('destination_boundaries') IS NOT NULL"))


def _token(live: LiveApp) -> str:
    response = _register(live, _id_token(live))
    assert response.status_code == 201, response.text
    return str(response.json()["tokens"]["access_token"])


def test_resolve_requires_authentication(catalog: str, live_app: LiveApp) -> None:
    response = _get(live_app, "/v1/destinations/resolve", near="-22.971,-43.182")
    assert response.status_code == 401


@pytest.mark.req("LOC-005")
def test_point_resolves_to_the_most_specific_destination(catalog: str, live_app: LiveApp) -> None:
    if not _postgis(catalog):
        pytest.skip("PostGIS not installed on this PostgreSQL (runs in CI)")
    token = _token(live_app)
    response = live_app.client.get(
        "/v1/destinations/resolve", params={"near": "-22.9711,-43.1822"}, headers=_auth(token)
    )
    body = _ok(response, "Destination")
    assert body["path"] == "brazil/rio-de-janeiro/copacabana"
    assert [a["path"] for a in body["ancestors"]] == ["brazil", "brazil/rio-de-janeiro"]
    # A point in Rio outside the seeded neighborhoods resolves to the city.
    city = live_app.client.get(
        "/v1/destinations/resolve", params={"near": "-22.85,-43.40"}, headers=_auth(token)
    )
    assert _ok(city, "Destination")["path"] == "brazil/rio-de-janeiro"


def test_points_outside_the_catalog_are_unresolvable(catalog: str, live_app: LiveApp) -> None:
    if not _postgis(catalog):
        pytest.skip("PostGIS not installed on this PostgreSQL (runs in CI)")
    token = _token(live_app)
    response = live_app.client.get(
        "/v1/destinations/resolve", params={"near": "0,-150"}, headers=_auth(token)
    )
    assert response.status_code == 422
    assert response.json()["code"] == "location_unresolvable"


def test_malformed_near_is_rejected(catalog: str, live_app: LiveApp) -> None:
    token = _token(live_app)
    response = live_app.client.get(
        "/v1/destinations/resolve", params={"near": "not-a-point"}, headers=_auth(token)
    )
    assert response.status_code == 422


# The initial launch set named in the PRD (DEST-005); the catalog adds more around it.
PRD_LAUNCH_CITIES = (
    "brazil/rio-de-janeiro",
    "portugal/lisbon",
    "spain/barcelona",
    "mexico/mexico-city",
    "france/paris",
    "germany/berlin",
    "united-kingdom/london",
    "united-states/new-york-city",
    "argentina/buenos-aires",
    "thailand/bangkok",
)


@pytest.mark.req("DEST-005", "I18N-002")
def test_the_prd_launch_cities_are_seeded_and_localized(catalog: str, live_app: LiveApp) -> None:
    for path in PRD_LAUNCH_CITIES:
        body = _ok(_get(live_app, "/v1/destinations/lookup", path=path), "Destination")
        assert body["kind"] == "city", path
        assert body["tagline"], path
    berlin = _ok(
        _get(live_app, "/v1/destinations/lookup", lang="pt-BR", path="germany/berlin"),
        "Destination",
    )
    assert (berlin["name"], berlin["country_name"]) == ("Berlim", "Alemanha")
    caba = _ok(_get(live_app, "/v1/destinations/search", q="caba"), "DestinationSummaryPage")
    assert caba["data"][0]["path"] == "argentina/buenos-aires"


def test_seeded_boundaries_match_postgis_availability(catalog: str) -> None:
    async def count(maker: async_sessionmaker[AsyncSession]) -> int:
        async with maker() as session:
            return int(
                await session.scalar(text("SELECT count(*) FROM destination_boundaries")) or 0
            )

    if not _postgis(catalog):
        pytest.skip("PostGIS not installed on this PostgreSQL (runs in CI)")

    async def run() -> int:
        engine = create_async_engine(catalog)
        try:
            return await count(async_sessionmaker(engine))
        finally:
            await engine.dispose()

    assert asyncio.run(run()) == 41
