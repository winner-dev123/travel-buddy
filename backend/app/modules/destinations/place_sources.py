"""Licensed place data sources (BL-4.01; DEST-003).

A :class:`PlaceSource` returns the public places around a destination together with the license
and attribution they were published under. Ingestion (``places.ingest``) stores them with
``data_freshness_at`` = when the source was read. Provider attributes (opening hours, website,
phone) are kept as published and always shown with that freshness, never generated (AI-004).

* :class:`OverpassSource`: OpenStreetMap through the Overpass API (ODbL 1.0; attribution
  "© OpenStreetMap contributors"). OSM terms allow storing and serving the data with attribution.
* :class:`DocumentSource`: a JSON document in the same shape (curated seeds, development, tests).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Literal, Protocol

import httpx

from app.core.time import Clock

PlaceStatus = Literal["active", "closed_permanently"]
CATEGORIES: Final = (
    "attraction",
    "restaurant",
    "cafe",
    "bar",
    "museum",
    "beach",
    "trail",
    "viewpoint",
    "park",
    "market",
    "lodging",
    "transit_hub",
    "other",
)
LOCALES: Final = ("en", "es", "pt-BR", "fr", "de")


@dataclass(frozen=True, slots=True)
class SourcePlace:
    provider_place_id: str
    name: str
    category: str
    lat: float
    lng: float
    names: Mapping[str, str] = field(default_factory=dict)  # locale -> localized name
    address: Mapping[str, str] | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)
    status: PlaceStatus = "active"
    popularity: float = 0.0  # a ranking hint for candidates and search ties


@dataclass(frozen=True, slots=True)
class SourceBatch:
    provider: str
    license: str
    attribution_text: str
    attribution_url: str | None
    retrieved_at: datetime
    places: tuple[SourcePlace, ...]


class PlaceSourceError(Exception):
    """The source could not be read (network, rate limit, malformed answer)."""


class PlaceSource(Protocol):
    async def fetch(self, *, lat: float, lng: float, radius_m: int, limit: int) -> SourceBatch: ...


# ─────────────────────────────── OpenStreetMap ───────────────────────────────

OSM_PROVIDER: Final = "osm"
OSM_LICENSE: Final = "ODbL-1.0"
OSM_ATTRIBUTION: Final = "© OpenStreetMap contributors"
OSM_COPYRIGHT_URL: Final = "https://www.openstreetmap.org/copyright"

# (tag, value) -> category; the first match wins, so specific tags come first.
_OSM_CATEGORIES: Final[tuple[tuple[str, str | None, str], ...]] = (
    ("tourism", "museum", "museum"),
    ("tourism", "gallery", "museum"),
    ("tourism", "viewpoint", "viewpoint"),
    ("tourism", "hotel", "lodging"),
    ("tourism", "hostel", "lodging"),
    ("tourism", "guest_house", "lodging"),
    ("tourism", "attraction", "attraction"),
    ("tourism", "theme_park", "attraction"),
    ("tourism", "zoo", "attraction"),
    ("tourism", "aquarium", "attraction"),
    ("amenity", "restaurant", "restaurant"),
    ("amenity", "food_court", "restaurant"),
    ("amenity", "cafe", "cafe"),
    ("amenity", "ice_cream", "cafe"),
    ("amenity", "bar", "bar"),
    ("amenity", "pub", "bar"),
    ("amenity", "marketplace", "market"),
    ("natural", "beach", "beach"),
    ("leisure", "beach_resort", "beach"),
    ("leisure", "park", "park"),
    ("leisure", "garden", "park"),
    ("route", "hiking", "trail"),
    ("highway", "path", "trail"),
    ("railway", "station", "transit_hub"),
    ("amenity", "bus_station", "transit_hub"),
    ("aeroway", "aerodrome", "transit_hub"),
    ("amenity", "ferry_terminal", "transit_hub"),
    ("historic", None, "attraction"),
)
# Published provider attributes we keep (and show with freshness); everything else is dropped.
_OSM_ATTRIBUTES: Final[Mapping[str, str]] = {
    "opening_hours": "opening_hours",
    "website": "website",
    "contact:website": "website",
    "phone": "phone",
    "contact:phone": "phone",
    "wheelchair": "wheelchair",
    "cuisine": "cuisine",
    "wikidata": "wikidata",
}
_OSM_NAME_TAGS: Final[Mapping[str, str]] = {
    "en": "name:en",
    "es": "name:es",
    "pt-BR": "name:pt",
    "fr": "name:fr",
    "de": "name:de",
}


def osm_category(tags: Mapping[str, str]) -> str | None:
    for key, value, category in _OSM_CATEGORIES:
        if key in tags and (value is None or tags[key] == value):
            return category
    return None


def osm_place(element: Mapping[str, Any]) -> SourcePlace | None:
    """One Overpass element (node, or way/relation with ``center``) as a place, or ``None``."""
    tags: Mapping[str, str] = element.get("tags") or {}
    name = (tags.get("name") or "").strip()
    category = osm_category(tags)
    if not name or category is None:
        return None
    if element.get("type") == "node":
        lat, lng = element.get("lat"), element.get("lon")
    else:
        center = element.get("center") or {}
        lat, lng = center.get("lat"), center.get("lon")
    if not isinstance(lat, int | float) or not isinstance(lng, int | float):
        return None
    address = {
        target: tags[source]
        for source, target in (
            ("addr:street", "line1"),
            ("addr:city", "locality"),
            ("addr:state", "region"),
            ("addr:postcode", "postal_code"),
        )
        if tags.get(source)
    }
    if tags.get("addr:street") and tags.get("addr:housenumber"):
        address["line1"] = f"{tags['addr:street']} {tags['addr:housenumber']}"
    country = tags.get("addr:country", "")
    if len(country) == 2 and country.isalpha():
        address["country_code"] = country.upper()
    attributes: dict[str, Any] = {}
    for source, target in _OSM_ATTRIBUTES.items():
        if tags.get(source) and target not in attributes:
            attributes[target] = tags[source][:500]
    closed = tags.get("disused") == "yes" or any(k.startswith("disused:") for k in tags)
    return SourcePlace(
        provider_place_id=f"{element.get('type')}/{element.get('id')}",
        name=name[:200],
        category=category,
        lat=float(lat),
        lng=float(lng),
        names={
            locale: tags[tag].strip()[:200]
            for locale, tag in _OSM_NAME_TAGS.items()
            if tags.get(tag, "").strip()
        },
        address=address or None,
        attributes=attributes,
        status="closed_permanently" if closed else "active",
        # OSM has no popularity: a Wikidata link or a website signals a notable place.
        popularity=10.0 if "wikidata" in tags else 3.0 if "website" in attributes else 1.0,
    )


_OVERPASS_SELECTORS: Final = (
    '["tourism"~"^(museum|gallery|viewpoint|attraction|theme_park|zoo|aquarium)$"]',
    '["amenity"~"^(restaurant|cafe|bar|pub|marketplace|food_court|ice_cream)$"]',
    '["natural"="beach"]',
    '["leisure"~"^(park|garden|beach_resort)$"]',
    '["historic"]',
)


def overpass_query(*, lat: float, lng: float, radius_m: int, limit: int) -> str:
    """One output per kind of place, each with an equal share of ``limit``, so dense kinds
    (restaurants) cannot crowd out the rest (museums, parks, beaches)."""
    around = f"(around:{radius_m},{lat:.6f},{lng:.6f})"
    each = max(1, limit // len(_OVERPASS_SELECTORS))
    body = "".join(
        f"nwr{selector}[name]{around};out center tags {each};" for selector in _OVERPASS_SELECTORS
    )
    return f"[out:json][timeout:90];{body}"


class OverpassSource:
    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        clock: Clock,
        endpoint: str = "https://overpass-api.de/api/interpreter",
        user_agent: str = "TravelBuddy/1.0 (place catalog ingestion)",
    ) -> None:
        self._http = http_client
        self._clock = clock
        self._endpoint = endpoint
        self._user_agent = user_agent

    async def fetch(self, *, lat: float, lng: float, radius_m: int, limit: int) -> SourceBatch:
        retrieved_at = self._clock.now()
        try:
            response = await self._http.post(
                self._endpoint,
                data={"data": overpass_query(lat=lat, lng=lng, radius_m=radius_m, limit=limit)},
                headers={"User-Agent": self._user_agent},
                timeout=90.0,
            )
        except httpx.HTTPError as exc:
            raise PlaceSourceError("Overpass unreachable") from exc
        if response.status_code != 200:
            raise PlaceSourceError(f"Overpass answered {response.status_code}")
        try:
            elements = response.json().get("elements", [])
        except ValueError as exc:
            raise PlaceSourceError("Overpass sent malformed JSON") from exc
        places = _unique(p for p in (osm_place(e) for e in elements) if p is not None)
        return SourceBatch(
            provider=OSM_PROVIDER,
            license=OSM_LICENSE,
            attribution_text=OSM_ATTRIBUTION,
            attribution_url=OSM_COPYRIGHT_URL,
            retrieved_at=retrieved_at,
            places=tuple(places[:limit]),
        )


# ─────────────────────────────── documents ───────────────────────────────


class DocumentSource:
    """Places from a JSON document::

        {"provider": "...", "license": "...", "attribution": {"text": "...", "url": null},
         "retrieved_at": "2026-11-01T00:00:00Z", "places": [{"id": "...", "name": "...",
         "category": "museum", "lat": 0, "lng": 0, "names": {}, "address": null,
         "attributes": {}, "status": "active"}]}

    Every place in the document is returned (the area arguments are ignored)."""

    def __init__(self, document: Mapping[str, Any]) -> None:
        self._document = document

    @classmethod
    def from_file(cls, path: Path) -> DocumentSource:
        return cls(json.loads(path.read_text(encoding="utf-8")))

    async def fetch(self, *, lat: float, lng: float, radius_m: int, limit: int) -> SourceBatch:
        doc = self._document
        attribution = doc.get("attribution") or {}
        places = []
        for raw in doc.get("places", []):
            category = raw.get("category")
            if category not in CATEGORIES:
                raise PlaceSourceError(f"unknown category {category!r}")
            places.append(
                SourcePlace(
                    provider_place_id=str(raw["id"]),
                    name=str(raw["name"]),
                    category=category,
                    lat=float(raw["lat"]),
                    lng=float(raw["lng"]),
                    names={k: v for k, v in (raw.get("names") or {}).items() if k in LOCALES},
                    address=raw.get("address"),
                    attributes=raw.get("attributes") or {},
                    status=raw.get("status", "active"),
                    popularity=float(raw.get("popularity", 0)),
                )
            )
        return SourceBatch(
            provider=str(doc["provider"]),
            license=str(doc["license"]),
            attribution_text=str(attribution.get("text") or doc["provider"]),
            attribution_url=attribution.get("url"),
            retrieved_at=datetime.fromisoformat(str(doc["retrieved_at"]).replace("Z", "+00:00")),
            places=tuple(places[:limit]),
        )


def _unique(places: Sequence[SourcePlace] | Any) -> list[SourcePlace]:
    seen: set[str] = set()
    found = []
    for place in places:
        if place.provider_place_id not in seen:
            seen.add(place.provider_place_id)
            found.append(place)
    return found
