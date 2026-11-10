"""Idempotent destination catalog loader (BL-1.05).

``python -m app.modules.destinations.seeding [--file PATH]`` upserts every destination by slug,
replaces its localizations and, where PostGIS is available, its approximate boundary (licensed
OSM polygons loaded by ``boundary_ingestion`` are kept). Safe to re-run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ids import uuid7
from app.modules.destinations.domain import SEGMENT_PATTERN, BoundingBox, Point
from app.modules.destinations.models import Destination, DestinationKind, DestinationLocalization

DEFAULT_FILE = Path(__file__).parent / "seed" / "launch_destinations.json"
# Initial editorial ranking until the nightly popularity job exists.
_BASE_POPULARITY = {"country": 50.0, "city": 100.0, "neighborhood": 30.0}
_FEATURED_BONUS = 50.0


@dataclass(frozen=True, slots=True)
class SeedResult:
    created: int
    updated: int
    boundaries: int


def slug_for(path: str, country_code: str, kind: str) -> str:
    segments = path.split("/")
    if kind == DestinationKind.COUNTRY:
        return segments[-1]
    return "-".join([*reversed(segments[1:]), country_code.lower()])


async def _postgis_ready(session: AsyncSession) -> bool:
    return bool(
        await session.scalar(text("SELECT to_regclass('destination_boundaries') IS NOT NULL"))
    )


async def load_catalog(session: AsyncSession, document: dict[str, Any]) -> SeedResult:
    """Upsert the catalog inside the caller's transaction (parents before children)."""
    entries = sorted(document["destinations"], key=lambda e: e["path"].count("/"))
    source = str(document.get("boundary_source", "unknown"))
    with_boundaries = await _postgis_ready(session)
    by_path: dict[str, Destination] = {}
    created = updated = boundaries = 0
    for entry in entries:
        path: str = entry["path"]
        segments = path.split("/")
        if not all(SEGMENT_PATTERN.fullmatch(s) for s in segments):
            raise ValueError(f"invalid path {path!r}")
        parent = by_path.get("/".join(segments[:-1])) if len(segments) > 1 else None
        if len(segments) > 1 and parent is None:
            raise ValueError(f"parent of {path!r} must precede it")
        centroid = Point(entry["centroid"]["lat"], entry["centroid"]["lng"])
        box = BoundingBox(**entry["bbox"])
        if not box.contains(centroid):
            raise ValueError(f"centroid of {path!r} is outside its bounding box")
        slug = slug_for(path, entry["country_code"], entry["kind"])
        row = await session.scalar(select(Destination).where(Destination.slug == slug))
        if row is None:
            row = Destination(id=uuid7(), slug=slug)
            session.add(row)
            created += 1
        else:
            updated += 1
        row.parent_id = parent.id if parent else None
        row.kind = entry["kind"]
        row.country_code = entry["country_code"]
        row.continent = entry["continent"]
        row.path_segment = segments[-1]
        row.default_name = entry["names"]["en"]
        row.centroid_lat = centroid.lat
        row.centroid_lng = centroid.lng
        row.time_zone = entry["time_zone"]
        row.path = [*(parent.path if parent else []), row.id]
        row.depth = len(segments) - 1
        row.is_featured = bool(entry.get("featured"))
        row.popularity_score = _BASE_POPULARITY.get(entry["kind"], 10.0) + (
            _FEATURED_BONUS if row.is_featured else 0.0
        )
        row.status = "active"
        # Licensed polygons loaded by boundary_ingestion survive re-seeding (ADR-0027).
        row.osm_relation_id = entry.get("osm_relation_id")
        await session.flush()

        await session.execute(
            delete(DestinationLocalization).where(DestinationLocalization.destination_id == row.id)
        )
        alt_names: dict[str, list[str]] = entry.get("alt_names", {})
        taglines: dict[str, str] = entry.get("taglines", {})
        for locale in sorted(set(entry["names"]) | set(taglines) | set(alt_names)):
            session.add(
                DestinationLocalization(
                    destination_id=row.id,
                    locale=locale,
                    name=entry["names"].get(locale, entry["names"]["en"]),
                    alt_names=alt_names.get(locale, []),
                    tagline=taglines.get(locale),
                )
            )
        if with_boundaries:
            await session.execute(
                text(
                    """
                    INSERT INTO destination_boundaries (destination_id, boundary, source)
                    VALUES (:id, ST_GeogFromText(:wkt), :source)
                    ON CONFLICT (destination_id) DO UPDATE
                       SET boundary = EXCLUDED.boundary, source = EXCLUDED.source,
                           updated_at = now()
                     WHERE destination_boundaries.source = EXCLUDED.source
                    """
                ),
                {"id": row.id, "wkt": f"SRID=4326;{box.as_multipolygon_wkt()}", "source": source},
            )
            boundaries += 1
        by_path[path] = row
    await session.flush()
    return SeedResult(created=created, updated=updated, boundaries=boundaries)


def read_document(path: Path = DEFAULT_FILE) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


async def _main(path: Path) -> None:
    from app.core.config import get_settings
    from app.core.db import Database

    settings = get_settings()
    database = Database(
        settings.database_url,
        pool_size=1,
        max_overflow=0,
        transaction_pooler=settings.database_transaction_pooler,
    )
    try:
        async with database.sessionmaker() as session, session.begin():
            result = await load_catalog(session, read_document(path))
        print(  # noqa: T201 - CLI output
            f"destinations: {result.created} created, {result.updated} updated, "
            f"{result.boundaries} boundaries"
        )
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Load the destination catalog")
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    args = parser.parse_args()
    asyncio.run(_main(args.file))


if __name__ == "__main__":
    main()
