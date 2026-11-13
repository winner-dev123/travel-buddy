"""Load the world gazetteer into the catalog (ADR-0035); ``world_catalog`` builds the files.

Idempotent and additive:

* Countries match by ISO code. Missing ones are created outside the directory.
* Towns match by GeoNames id; a town that is a launch city only adds its population, region and
  GeoNames id to the editorial row. New towns hang directly under their country with the path
  segment chosen at build time, so paths and slugs never change between runs.
* Attractions become places (provider ``wikidata``) of the town they belong to, by the same rule
  the API uses to resolve a point (``belonging``), within 50 km. A place already
  imported from OpenStreetMap with the same Wikidata id is not duplicated, and an editorial
  takedown (``hidden``) survives re-loading.

Gazetteer rows an editor has listed (``in_directory``) keep their editorial names.
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from sqlalchemy import delete, insert, literal_column, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.modules.destinations.models import Destination as DestinationRow
from app.modules.destinations.models import DestinationLocalization, PlaceLocalization
from app.modules.destinations.models import Place as PlaceRow
from app.modules.destinations.world_catalog import (
    ATTRACTIONS_FILE,
    CITIES_FILE,
    WIKIDATA_ATTRIBUTION,
    WIKIDATA_LICENSE,
    WIKIDATA_PROVIDER,
    WIKIDATA_URL,
    belonging,
    distance_km,
    fold,
    read_records,
    town_reach_km,
)

BATCH: Final = 1000
ATTRACTION_MAX_KM: Final = 50.0
COUNTRY_POPULARITY: Final = 40.0
_CELL_DEGREES: Final = 0.5


def chunks[T](items: Sequence[T], size: int = BATCH) -> Iterator[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def town_popularity(population: int | None) -> float:
    """Search tie-break for gazetteer towns: 37 for 5,000 people, 71 for 12 million (launch
    cities are 100-150)."""
    return round(10.0 * math.log10(max(0, population or 0) + 1), 2)


@dataclass(frozen=True, slots=True)
class WorldLoadResult:
    countries_created: int
    countries_updated: int
    towns_created: int
    towns_updated: int
    towns_skipped: int
    places_created: int
    places_updated: int
    places_skipped: int


@dataclass(frozen=True, slots=True)
class _Known:
    id: uuid.UUID
    kind: str
    path: list[uuid.UUID]
    path_segment: str
    in_directory: bool
    geonames_id: int | None


@dataclass(frozen=True, slots=True)
class TownPoint:
    id: uuid.UUID
    lat: float
    lng: float
    population: int | None
    folded_name: str


class TownIndex:
    """Towns in 0.5° cells: the town a point belongs to (``belonging``), as in
    ``service.nearest_town``."""

    def __init__(self, towns: Iterable[TownPoint]) -> None:
        self._cells: dict[tuple[int, int], list[TownPoint]] = defaultdict(list)
        for town in towns:
            self._cells[self._cell(town.lat, town.lng)].append(town)

    @staticmethod
    def _cell(lat: float, lng: float) -> tuple[int, int]:
        return (math.floor(lat / _CELL_DEGREES), math.floor(lng / _CELL_DEGREES))

    def nearest(self, lat: float, lng: float, *, max_km: float) -> TownPoint | None:
        row, col = self._cell(lat, lng)
        width_km = 111.32 * _CELL_DEGREES * max(0.2, math.cos(math.radians(lat)))
        span = 1 + math.ceil(max_km / width_km)
        best: tuple[float, float, TownPoint] | None = None
        for r in range(row - 2, row + 3):
            for c in range(col - span, col + span + 1):
                for town in self._cells.get((r, c), ()):
                    distance = distance_km(lat, lng, town.lat, town.lng)
                    if distance > max_km:
                        continue
                    score = belonging(distance, town_reach_km(town.population))
                    key = (score, distance, town)
                    if best is None or key[:2] < best[:2]:
                        best = key
        return best[2] if best else None


def _localization_rows(
    destination_id: uuid.UUID, default: str, names: Mapping[str, str], alt: Sequence[str]
) -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {
        locale: {
            "destination_id": destination_id,
            "locale": locale,
            "name": name,
            "alt_names": [],
            "tagline": None,
        }
        for locale, name in names.items()
    }
    if alt:
        rows.setdefault(
            "en",
            {
                "destination_id": destination_id,
                "locale": "en",
                "name": default,
                "alt_names": [],
                "tagline": None,
            },
        )["alt_names"] = list(alt)
    return list(rows.values())


async def _replace_localizations(
    session: AsyncSession, ids: Sequence[uuid.UUID], rows: Sequence[dict[str, Any]]
) -> None:
    for id_part in chunks(ids):
        await session.execute(
            delete(DestinationLocalization).where(
                DestinationLocalization.destination_id.in_(id_part)
            )
        )
    for row_part in chunks(rows):
        await session.execute(insert(DestinationLocalization), list(row_part))


async def load_world(
    session: AsyncSession,
    city_records: Iterable[Mapping[str, Any]],
    attraction_records: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
) -> WorldLoadResult:
    """Upsert inside the caller's transaction (see the module docstring)."""
    records = list(city_records)
    continents = {r["code"]: r["continent"] for r in records if r["type"] == "country"}
    known_rows = (
        await session.execute(
            select(
                DestinationRow.id,
                DestinationRow.kind,
                DestinationRow.country_code,
                DestinationRow.parent_id,
                DestinationRow.path,
                DestinationRow.path_segment,
                DestinationRow.slug,
                DestinationRow.in_directory,
                DestinationRow.geonames_id,
            )
        )
    ).all()
    by_id = {
        r.id: _Known(r.id, r.kind, list(r.path), r.path_segment, r.in_directory, r.geonames_id)
        for r in known_rows
    }
    by_path = {
        "/".join(by_id[i].path_segment for i in known.path if i in by_id): known
        for known in by_id.values()
    }
    by_geonames = {k.geonames_id: k for k in by_id.values() if k.geonames_id is not None}
    countries = {r.country_code: by_id[r.id] for r in known_rows if r.kind == "country"}
    slugs = {r.slug for r in known_rows}
    siblings = {(r.parent_id, r.path_segment) for r in known_rows}

    inserts: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    localized_ids: list[uuid.UUID] = []
    localizations: list[dict[str, Any]] = []
    countries_created = countries_updated = 0
    towns_created = towns_updated = towns_skipped = 0

    for record in (r for r in records if r["type"] == "country"):
        code = record["code"]
        existing = countries.get(code) or by_path.get(record.get("launch_path", ""))
        geonames_id = int(record["geonames_id"])
        if existing is None:
            segment = record["segment"]
            if segment in slugs or (None, segment) in siblings:
                continue
            new_id = uuid7()
            inserts.append(
                {
                    "id": new_id,
                    "parent_id": None,
                    "kind": "country",
                    "country_code": code,
                    "continent": record["continent"],
                    "slug": segment,
                    "path_segment": segment,
                    "default_name": record["name"],
                    "centroid_lat": record["lat"],
                    "centroid_lng": record["lng"],
                    "time_zone": record["time_zone"],
                    "path": [new_id],
                    "depth": 0,
                    "geonames_id": geonames_id if geonames_id not in by_geonames else None,
                    "population": record.get("population"),
                    "popularity_score": COUNTRY_POPULARITY,
                    "in_directory": False,
                    "status": "active",
                }
            )
            countries[code] = _Known(new_id, "country", [new_id], segment, False, geonames_id)
            slugs.add(segment)
            siblings.add((None, segment))
            localized_ids.append(new_id)
            localizations += _localization_rows(new_id, record["name"], record["names"], [])
            countries_created += 1
            continue
        change: dict[str, Any] = {"id": existing.id, "population": record.get("population")}
        if existing.geonames_id is None and geonames_id not in by_geonames:
            change["geonames_id"] = geonames_id
            by_geonames[geonames_id] = existing
        if not existing.in_directory:
            change |= {
                "default_name": record["name"],
                "centroid_lat": record["lat"],
                "centroid_lng": record["lng"],
                "time_zone": record["time_zone"],
                "continent": record["continent"],
            }
            localized_ids.append(existing.id)
            localizations += _localization_rows(existing.id, record["name"], record["names"], [])
        updates.append(change)
        countries_updated += 1

    for record in (r for r in records if r["type"] == "town"):
        geonames_id = int(record["geonames_id"])
        population = record.get("population")
        existing = by_geonames.get(geonames_id)
        if existing is None and record.get("launch_path"):
            existing = by_path.get(record["launch_path"])
        if existing is not None:
            change = {
                "id": existing.id,
                "population": population,
                "region_name": record.get("region"),
            }
            if existing.geonames_id is None:
                change["geonames_id"] = geonames_id
            if not existing.in_directory:
                change |= {
                    "default_name": record["name"],
                    "centroid_lat": record["lat"],
                    "centroid_lng": record["lng"],
                    "time_zone": record["time_zone"],
                    "popularity_score": town_popularity(population),
                }
                localized_ids.append(existing.id)
                localizations += _localization_rows(
                    existing.id, record["name"], record["names"], record.get("alt", [])
                )
            updates.append(change)
            towns_updated += 1
            continue
        country = countries.get(record["code"])
        segment = record.get("segment")
        if record.get("launch_path") or country is None or not segment:
            towns_skipped += 1  # a launch city not seeded here, or an unknown country
            continue
        slug = f"{segment}-{record['code'].lower()}"
        if slug in slugs or (country.id, segment) in siblings:
            towns_skipped += 1
            continue
        new_id = uuid7()
        inserts.append(
            {
                "id": new_id,
                "parent_id": country.id,
                "kind": "city",
                "country_code": record["code"],
                "continent": continents[record["code"]],
                "slug": slug,
                "path_segment": segment,
                "default_name": record["name"],
                "centroid_lat": record["lat"],
                "centroid_lng": record["lng"],
                "time_zone": record["time_zone"],
                "path": [*country.path, new_id],
                "depth": len(country.path),
                "geonames_id": geonames_id,
                "population": population,
                "region_name": record.get("region"),
                "popularity_score": town_popularity(population),
                "in_directory": False,
                "status": "active",
            }
        )
        slugs.add(slug)
        siblings.add((country.id, segment))
        by_geonames[geonames_id] = _Known(
            new_id, "city", [*country.path, new_id], segment, False, geonames_id
        )
        localized_ids.append(new_id)
        localizations += _localization_rows(
            new_id, record["name"], record["names"], record.get("alt", [])
        )
        towns_created += 1

    # Countries first: towns reference them (parents precede children in ``inserts``).
    for part in chunks(inserts):
        await session.execute(insert(DestinationRow), list(part))
    for part in chunks(updates):
        await session.execute(update(DestinationRow), list(part))
    await _replace_localizations(session, localized_ids, localizations)

    places = await _load_attractions(session, attraction_records, now=now)
    return WorldLoadResult(
        countries_created=countries_created,
        countries_updated=countries_updated,
        towns_created=towns_created,
        towns_updated=towns_updated,
        towns_skipped=towns_skipped,
        places_created=places[0],
        places_updated=places[1],
        places_skipped=places[2],
    )


async def _load_attractions(
    session: AsyncSession, records: Iterable[Mapping[str, Any]], *, now: datetime
) -> tuple[int, int, int]:
    towns = TownIndex(
        TownPoint(r.id, r.centroid_lat, r.centroid_lng, r.population, fold(r.default_name))
        for r in (
            await session.execute(
                select(
                    DestinationRow.id,
                    DestinationRow.centroid_lat,
                    DestinationRow.centroid_lng,
                    DestinationRow.population,
                    DestinationRow.default_name,
                ).where(DestinationRow.kind == "city", DestinationRow.status == "active")
            )
        ).all()
    )
    in_osm = set(
        (
            await session.scalars(
                select(PlaceRow.attributes["wikidata"].astext).where(
                    PlaceRow.provider == "osm", PlaceRow.attributes.has_key("wikidata")
                )
            )
        ).all()
    )
    rows: list[dict[str, Any]] = []
    names: dict[str, Mapping[str, str]] = {}
    skipped = 0
    for record in records:
        qid = record["qid"]
        town = towns.nearest(record["lat"], record["lng"], max_km=ATTRACTION_MAX_KM)
        if qid in in_osm or town is None or fold(record["name"]) == town.folded_name:
            skipped += 1  # already from OSM, far from every town, or the town itself
            continue
        rows.append(
            {
                "id": uuid7(),
                "destination_id": town.id,
                "provider": WIKIDATA_PROVIDER,
                "provider_place_id": qid,
                "category": record["category"],
                "default_name": record["name"],
                "lat": record["lat"],
                "lng": record["lng"],
                "address": None,
                "license": WIKIDATA_LICENSE,
                "attribution_text": WIKIDATA_ATTRIBUTION,
                "attribution_url": f"{WIKIDATA_URL}wiki/{qid}",
                "data_freshness_at": now,
                "attributes": {"wikidata": qid},
                "status": "active",
                "popularity_score": float(record["sitelinks"]),
                "updated_at": now,
            }
        )
        names[qid] = record["names"]
    base = pg_insert(PlaceRow)
    excluded = base.excluded
    statement: Any = base.on_conflict_do_update(
        index_elements=[PlaceRow.provider, PlaceRow.provider_place_id],
        set_={
            "category": excluded.category,
            "default_name": excluded.default_name,
            "lat": excluded.lat,
            "lng": excluded.lng,
            "license": excluded.license,
            "attribution_text": excluded.attribution_text,
            "attribution_url": excluded.attribution_url,
            "data_freshness_at": excluded.data_freshness_at,
            "attributes": excluded.attributes,
            "popularity_score": excluded.popularity_score,
            "updated_at": excluded.updated_at,
            # An editorial takedown survives re-loading.
            "status": text(
                "CASE WHEN places.status = 'hidden' THEN 'hidden' ELSE excluded.status END"
            ),
        },
    ).returning(
        PlaceRow.id,
        PlaceRow.provider_place_id,
        literal_column("(xmax = 0)").label("inserted"),
    )
    created = updated = 0
    ids: dict[str, uuid.UUID] = {}
    for row_part in chunks(rows):
        for row in (await session.execute(statement, list(row_part))).all():
            ids[row.provider_place_id] = row.id
            if row.inserted:
                created += 1
            else:
                updated += 1
    place_ids = list(ids.values())
    for id_part in chunks(place_ids):
        await session.execute(
            delete(PlaceLocalization).where(PlaceLocalization.place_id.in_(id_part))
        )
    localization_rows = [
        {"place_id": ids[qid], "locale": locale, "name": name}
        for qid, localized in names.items()
        if qid in ids
        for locale, name in localized.items()
    ]
    for part in chunks(localization_rows):
        await session.execute(insert(PlaceLocalization), list(part))
    return created, updated, skipped


async def run_load(
    cities_file: Path = CITIES_FILE, attractions_file: Path = ATTRACTIONS_FILE
) -> WorldLoadResult:
    from app.core.config import get_settings
    from app.core.db import Database
    from app.core.time import SystemClock

    settings = get_settings()
    database = Database.from_settings(settings, pool_size=1, max_overflow=0)
    try:
        async with database.sessionmaker() as session, session.begin():
            result = await load_world(
                session,
                read_records(cities_file),
                read_records(attractions_file),
                now=SystemClock().now(),
            )
    finally:
        await database.dispose()
    print(  # noqa: T201 - CLI output
        f"countries: {result.countries_created} created, {result.countries_updated} updated; "
        f"towns: {result.towns_created} created, {result.towns_updated} updated, "
        f"{result.towns_skipped} skipped; places: {result.places_created} created, "
        f"{result.places_updated} updated, {result.places_skipped} skipped"
    )
    return result
