"""Places catalog end to end (BL-4.01; DEST-003, LOC-009, AI-003): ingestion from a licensed
source, reads with attribution and freshness, search, nearby, AI grounding and trip items."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.destinations.place_ingestion import ingest_destination
from app.modules.destinations.place_sources import DocumentSource
from app.modules.destinations.places import IngestResult
from tests.contract_schemas import assert_matches_contract
from tests.integration.conftest import LiveApp, db_scalar
from tests.integration.test_destinations import catalog  # noqa: F401 - module-scoped fixture
from tests.integration.test_identity_flows import _auth
from tests.integration.test_posts import _destination, _problem, _tick, _user, app  # noqa: F401

pytestmark = pytest.mark.integration

LISBON = (38.7223, -9.1393)


def _document(**overrides: Any) -> dict[str, Any]:
    lat, lng = LISBON
    places = [
        {
            "id": "belem-tower",
            "name": "Torre de Belém",
            "names": {"en": "Belém Tower", "pt-BR": "Torre de Belém"},
            "category": "attraction",
            "lat": lat + 0.004,
            "lng": lng,
            "address": {"locality": "Lisboa", "country_code": "PT"},
            "attributes": {"opening_hours": "Tu-Su 10:00-17:30"},
            "popularity": 10,
        },
        {
            "id": "gulbenkian",
            "name": "Museu Calouste Gulbenkian",
            "category": "museum",
            "lat": lat + 0.001,
            "lng": lng,
            "popularity": 8,
        },
        {
            "id": "time-out-market",
            "name": "Time Out Market",
            "category": "market",
            "lat": lat + 0.002,
            "lng": lng,
            "popularity": 5,
        },
        {
            "id": "far-away",
            "name": "Cabo da Roca",
            "category": "viewpoint",
            "lat": lat,
            "lng": lng - 0.4,  # ~35 km west
            "popularity": 9,
        },
    ]
    return {
        "provider": "test-catalog",
        "license": "CC0-1.0",
        "attribution": {"text": "Test catalog", "url": "https://example.org/catalog"},
        "retrieved_at": "2026-11-01T00:00:00Z",
        "places": places,
        **overrides,
    }


def _ingest(live: LiveApp, document: dict[str, Any], path: str = "portugal/lisbon") -> IngestResult:
    async def run() -> IngestResult:
        engine = create_async_engine(live.db_url)
        try:
            async with async_sessionmaker(engine)() as session, session.begin():
                return await ingest_destination(
                    session, path=path, source=DocumentSource(document), clock=live.clock
                )
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _place_id(live: LiveApp, provider_place_id: str) -> str:
    return str(
        db_scalar(
            live.db_url,
            "SELECT id FROM places WHERE provider_place_id = :p",
            p=provider_place_id,
        )
    )


@pytest.fixture(autouse=True)
def _fresh_catalog(app: LiveApp) -> Iterator[None]:  # noqa: F811
    clear = (
        "WITH a AS (DELETE FROM ai_generations RETURNING 1), "
        "p AS (DELETE FROM places RETURNING 1) SELECT (SELECT count(*) FROM a) + count(*) FROM p"
    )
    db_scalar(app.db_url, clear)
    yield
    db_scalar(app.db_url, clear)


@pytest.mark.req("DEST-003", "GUIDE-002")
def test_ingested_places_carry_attribution_freshness_and_localized_names(
    app: LiveApp,  # noqa: F811
) -> None:
    assert _ingest(app, _document()) == IngestResult(created=4, updated=0)
    tower = _place_id(app, "belem-tower")
    response = app.client.get(f"/v1/places/{tower}", headers={"Accept-Language": "pt-BR"})
    assert response.status_code == 200, response.text  # anonymous reads are allowed
    assert_matches_contract(response.json(), "Place")
    place = response.json()
    assert place["name"] == "Torre de Belém"
    assert place["category"] == "attraction"
    assert place["destination_id"] == _destination(app, "portugal/lisbon")
    assert place["attribution"] == {
        "provider": "test-catalog",
        "license": "CC0-1.0",
        "text": "Test catalog",
        "url": "https://example.org/catalog",
    }
    assert place["attributes"] == {"opening_hours": "Tu-Su 10:00-17:30"}
    assert place["data_freshness_at"].startswith("2026-11-01")
    assert place["data_stale"] is False
    assert place["address"] == {"locality": "Lisboa", "country_code": "PT"}
    english = app.client.get(f"/v1/places/{tower}", headers={"Accept-Language": "en"}).json()
    assert english["name"] == "Belém Tower"

    # Re-ingestion refreshes, an editorial takedown survives it, stale data is flagged.
    db_scalar(
        app.db_url,
        "UPDATE places SET status = 'hidden' WHERE provider_place_id = 'gulbenkian' RETURNING 1",
    )
    refreshed = _ingest(app, _document(retrieved_at="2026-11-09T00:00:00Z"))
    assert refreshed == IngestResult(created=0, updated=4)
    gulbenkian = _place_id(app, "gulbenkian")
    _problem(app.client.get(f"/v1/places/{gulbenkian}"), 404, "not_found")
    assert (
        app.client.get(f"/v1/places/{tower}").json()["data_freshness_at"].startswith("2026-11-09")
    )
    db_scalar(
        app.db_url,
        "UPDATE places SET data_freshness_at = now() - interval '200 days' "
        "WHERE id = :i RETURNING 1",
        i=uuid.UUID(tower),
    )
    assert app.client.get(f"/v1/places/{tower}").json()["data_stale"] is True
    _problem(app.client.get(f"/v1/places/{uuid.uuid4()}"), 404, "not_found")


@pytest.mark.req("DEST-003")
def test_search_within_a_destination_and_its_ancestors(app: LiveApp) -> None:  # noqa: F811
    _ingest(app, _document())
    token, _ = _user(app)
    lisbon = _destination(app, "portugal/lisbon")

    def search(q: str, destination: str, **params: str) -> list[str]:
        response = app.client.get(
            "/v1/places/search",
            params={"q": q, "destination_id": destination, **params},
            headers={**_auth(token), "Accept-Language": "en"},
        )
        assert response.status_code == 200, response.text
        assert_matches_contract(response.json(), "PlacePage")
        return [p["name"] for p in response.json()["data"]]

    assert search("belem", lisbon) == ["Belém Tower"]  # accent- and case-insensitive
    assert search("gulbenkan", lisbon) == ["Museu Calouste Gulbenkian"]  # typo-tolerant
    assert search("belem", _destination(app, "portugal")) == ["Belém Tower"]  # ancestors match
    assert search("belem", _destination(app, "brazil")) == []
    assert search("museu", lisbon, category="market") == []
    _problem(
        app.client.get(
            "/v1/places/search",
            params={"q": "belem", "destination_id": lisbon, "category": "spaceport"},
            headers=_auth(token),
        ),
        422,
        "validation_failed",
    )
    anonymous = app.client.get("/v1/places/search", params={"q": "be", "destination_id": lisbon})
    assert anonymous.status_code == 401


@pytest.mark.req("LOC-009", "DEST-003")
def test_nearby_orders_by_distance_and_pages_with_cursors(app: LiveApp) -> None:  # noqa: F811
    _ingest(app, _document())
    token, _ = _user(app)
    near = f"{LISBON[0]},{LISBON[1]}"

    def nearby(**params: Any) -> Any:
        return app.client.get(
            "/v1/places/nearby", params={"near": near, **params}, headers=_auth(token)
        )

    first = nearby(radius_m=1000, limit=2)
    assert first.status_code == 200, first.text
    assert_matches_contract(first.json(), "PlacePage")
    page = first.json()
    assert [p["name"] for p in page["data"]] == ["Museu Calouste Gulbenkian", "Time Out Market"]
    cursor = page["page"]["next_cursor"]
    assert cursor
    second = nearby(radius_m=1000, limit=2, cursor=cursor).json()
    # Cabo da Roca is 35 km out; names default to English without Accept-Language.
    assert [p["name"] for p in second["data"]] == ["Belém Tower"]
    assert second["page"]["next_cursor"] is None
    _problem(nearby(radius_m=2000, limit=2, cursor=cursor), 400, "invalid_cursor")
    assert [p["name"] for p in nearby(category="museum,viewpoint").json()["data"]] == [
        "Museu Calouste Gulbenkian"
    ]
    assert len(nearby(radius_m=20000).json()["data"]) == 3
    _problem(nearby(near="nowhere"), 422, "validation_failed")
    assert app.client.get("/v1/places/nearby", params={"near": near}).status_code == 401


@pytest.mark.req("AI-003", "AI-002", "TRIP-001")
def test_ai_itineraries_are_grounded_on_catalog_places(app: LiveApp) -> None:  # noqa: F811
    _ingest(app, _document())
    token, _ = _user(app)
    lisbon = _destination(app, "portugal/lisbon")
    created = app.client.post(
        "/v1/ai/itineraries/generate",
        headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())},
        json={"destination_id": lisbon, "start_date": "2026-12-04", "end_date": "2026-12-05"},
    )
    assert created.status_code == 202, created.text
    _tick(app)
    done = app.client.get(f"/v1/ai/generations/{created.json()['id']}", headers=_auth(token))
    assert_matches_contract(done.json(), "AIGeneration")
    proposal = done.json()["result"]
    first = proposal["itinerary"]["days"][0]["items"][0]
    assert first["unverified"] is False
    assert first["place"]["name"] == "Belém Tower"  # the most popular candidate
    assert first["place_data_freshness_at"].startswith("2026-11-01")
    [attribution] = first["source_attribution"]
    assert attribution["kind"] == "catalog_place"
    assert attribution["provider"] == "test-catalog"
    assert attribution["ref_id"] == _place_id(app, "belem-tower")
    kinds = [s["kind"] for s in proposal["itinerary"]["sources"]]
    assert "licensed_provider" in kinds
    assert proposal["freshness"]["catalog_data_as_of"].startswith("2026-11-01")
    prompt = app.client.app.state.ai_provider.calls[-1]  # type: ignore[attr-defined]
    assert "Belém Tower" in prompt.user
    assert "Tu-Su 10:00" not in prompt.user  # licensed attributes never reach the model

    trip = app.client.post(
        "/v1/trips",
        headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "title": "Lisbon",
            "start_date": "2026-12-04",
            "end_date": "2026-12-05",
            "destination_ids": [lisbon],
        },
    ).json()
    applied = app.client.post(
        f"/v1/trips/{trip['id']}/apply-itinerary",
        headers={**_auth(token), "If-Match": '"1"'},
        json={"generation_id": created.json()["id"], "mode": "replace"},
    )
    assert applied.status_code == 200, applied.text
    assert_matches_contract(applied.json(), "Trip")
    item = applied.json()["days"][0]["items"][0]
    assert item["place"]["name"] == "Belém Tower"
    assert item["unverified"] is False
    assert item["data_freshness_at"].startswith("2026-11-01")


@pytest.mark.req("TRIP-001", "DEST-003")
def test_trip_items_reference_listed_places_only(app: LiveApp) -> None:  # noqa: F811
    _ingest(app, _document())
    token, _ = _user(app)
    trip = app.client.post(
        "/v1/trips",
        headers={**_auth(token), "Idempotency-Key": str(uuid.uuid4())},
        json={
            "title": "Lisbon",
            "start_date": "2026-12-04",
            "end_date": "2026-12-04",
            "destination_ids": [_destination(app, "portugal/lisbon")],
        },
    ).json()
    url = f"/v1/trips/{trip['id']}/days/{trip['days'][0]['id']}/items"
    headers = {**_auth(token), "If-Match": '"1"'}
    unknown = {"kind": "activity", "title": "Somewhere", "place_id": str(uuid.uuid4())}
    _problem(app.client.post(url, headers=headers, json=unknown), 422, "validation_failed")
    museum = {"kind": "activity", "title": "Museum", "place_id": _place_id(app, "gulbenkian")}
    added = app.client.post(url, headers=headers, json=museum)
    assert added.status_code == 201, added.text
    assert added.json()["days"][0]["items"][0]["place"]["category"] == "museum"
    # Removing the place from the catalog leaves the item, without the place.
    db_scalar(app.db_url, "DELETE FROM places WHERE provider_place_id = 'gulbenkian' RETURNING 1")
    after = app.client.get(f"/v1/trips/{trip['id']}", headers=_auth(token)).json()
    assert after["days"][0]["items"][0]["place"] is None
