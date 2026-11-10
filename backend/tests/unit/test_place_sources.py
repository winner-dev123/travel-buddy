"""Licensed place sources: OpenStreetMap mapping and the Overpass adapter (BL-4.01; DEST-003)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from app.core.time import FixedClock
from app.modules.destinations.place_sources import (
    OSM_ATTRIBUTION,
    OSM_LICENSE,
    DocumentSource,
    OverpassSource,
    PlaceSourceError,
    osm_category,
    osm_place,
    overpass_query,
)

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def _node(**tags: str) -> dict[str, Any]:
    return {"type": "node", "id": 42, "lat": 38.6916, "lon": -9.2160, "tags": tags}


def test_osm_tags_map_to_catalog_categories() -> None:
    assert osm_category({"tourism": "museum"}) == "museum"
    assert osm_category({"amenity": "pub"}) == "bar"
    assert osm_category({"natural": "beach"}) == "beach"
    assert osm_category({"historic": "monument"}) == "attraction"  # any historic value
    assert osm_category({"tourism": "museum", "historic": "yes"}) == "museum"  # specific first
    assert osm_category({"shop": "bakery"}) is None


@pytest.mark.req("DEST-003")
def test_an_osm_element_becomes_a_place_with_published_attributes_only() -> None:
    place = osm_place(
        _node(
            name="Torre de Belém",
            **{
                "name:en": "Belém Tower",
                "name:pt": "Torre de Belém",
                "tourism": "attraction",
                "historic": "tower",
                "opening_hours": "Tu-Su 10:00-17:30",
                "website": "https://example.org",
                "addr:street": "Av. Brasília",
                "addr:city": "Lisboa",
                "addr:country": "pt",
                "wikidata": "Q207011",
                "operator:secret": "dropped",
            },
        )
    )
    assert place is not None
    assert place.provider_place_id == "node/42"
    assert place.category == "attraction"
    assert place.names == {"en": "Belém Tower", "pt-BR": "Torre de Belém"}
    assert place.address == {"line1": "Av. Brasília", "locality": "Lisboa", "country_code": "PT"}
    assert place.attributes == {
        "opening_hours": "Tu-Su 10:00-17:30",
        "website": "https://example.org",
        "wikidata": "Q207011",
    }
    assert place.popularity == 10.0
    assert place.status == "active"


def test_ways_use_their_center_and_unusable_elements_are_skipped() -> None:
    way = {
        "type": "way",
        "id": 7,
        "center": {"lat": 1.5, "lon": 2.5},
        "tags": {"name": "Park", "leisure": "park"},
    }
    place = osm_place(way)
    assert place is not None
    assert (place.lat, place.lng, place.provider_place_id) == (1.5, 2.5, "way/7")
    assert osm_place(_node(tourism="museum")) is None  # no name
    assert osm_place(_node(name="Bakery", shop="bakery")) is None  # no catalog category
    assert osm_place({"type": "way", "id": 1, "tags": {"name": "X", "leisure": "park"}}) is None
    closed = osm_place(_node(name="Old Bar", amenity="bar", **{"disused:amenity": "bar"}))
    assert closed is not None
    assert closed.status == "closed_permanently"


def test_overpass_query_targets_named_places_around_the_point() -> None:
    query = overpass_query(lat=38.7223, lng=-9.1393, radius_m=6000, limit=300)
    assert "(around:6000,38.722300,-9.139300)" in query
    assert "[name]" in query
    assert query.startswith("[out:json]")
    assert query.count("out center tags 60;") == 5  # an equal share per kind of place


async def test_overpass_source_reads_dedupes_and_attributes() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        node = _node(name="Museu", tourism="museum")
        return httpx.Response(200, json={"elements": [node, node, _node(shop="x")]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        batch = await OverpassSource(client, clock=FixedClock(NOW)).fetch(
            lat=38.7, lng=-9.1, radius_m=1000, limit=10
        )
    assert [p.name for p in batch.places] == ["Museu"]
    assert (batch.provider, batch.license, batch.attribution_text) == (
        "osm",
        OSM_LICENSE,
        OSM_ATTRIBUTION,
    )
    assert batch.retrieved_at == NOW
    [request] = seen
    assert request.method == "POST"
    assert "around:1000" in parse_qs(request.content.decode())["data"][0]
    assert request.headers["user-agent"].startswith("TravelBuddy/")


@pytest.mark.parametrize(
    "response",
    [httpx.Response(429, text="slow down"), httpx.Response(200, text="<html>")],
)
async def test_overpass_failures_are_source_errors(response: httpx.Response) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: response)) as client:
        with pytest.raises(PlaceSourceError):
            await OverpassSource(client, clock=FixedClock(NOW)).fetch(
                lat=0, lng=0, radius_m=100, limit=1
            )


async def test_document_source_validates_categories() -> None:
    document = {
        "provider": "test",
        "license": "CC0-1.0",
        "retrieved_at": "2026-11-01T00:00:00Z",
        "places": [{"id": "1", "name": "X", "category": "spaceport", "lat": 0, "lng": 0}],
    }
    with pytest.raises(PlaceSourceError):
        await DocumentSource(document).fetch(lat=0, lng=0, radius_m=1, limit=1)
