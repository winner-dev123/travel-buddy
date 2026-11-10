"""Guide and audio tour authoring loader (BL-4.07).

``python -m app.modules.guides.seeding [--file PATH]`` validates a content document and publishes
it: each guide is upserted by ``(destination, locale, slug, version)``, published, and older
versions of the same guide are retired. Safe to re-run. Sections are validated against the
structured format (prose or FAQ, GUIDE-006) before anything is written.

Document::

    {"guides": [{"destination": "portugal/lisbon", "slug": "lisbon-essentials", "locale": "en",
                 "version": 1, "tier": "free", "title": "...", "summary": "...",
                 "content_license": "...", "attribution": null, "sections": [...]}],
     "audio_tours": [{"destination": "...", "slug": "...", "locale": "en", "version": 1,
                      "tier": "premium", "title": "...", "description": "...",
                      "content_license": "...",
                      "stops": [{"place_id": "<uuid>", "audio_media_id": "<uuid>",
                                 "title": "...", "transcript": null, "trigger_radius_m": 40,
                                 "duration_s": 180}]}]}
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import Database
from app.core.time import SystemClock
from app.modules.destinations.service import id_for_path, set_has_guides
from app.modules.guides.models import AudioTour, AudioTourStop, DestinationGuide
from app.modules.guides.schemas import GuideSection

DEFAULT_FILE = Path(__file__).parent / "seed" / "launch_guides.json"
_SECTIONS = TypeAdapter(list[GuideSection])


@dataclass(frozen=True, slots=True)
class SeedResult:
    guides: int
    audio_tours: int


async def _destination(session: AsyncSession, path: str) -> uuid.UUID:
    destination_id = await id_for_path(session, path)
    if destination_id is None:
        raise ValueError(f"unknown destination {path!r}")
    return destination_id


async def _publish(
    session: AsyncSession,
    model: Any,  # DestinationGuide or AudioTour (same versioning columns)
    key: dict[str, Any],
    values: dict[str, Any],
    now: datetime,
) -> Any:
    row = await session.scalar(select(model).filter_by(**key))
    if row is None:
        row = model(**key, **values, status="published", published_at=now, updated_at=now)
        session.add(row)
    else:
        for name, value in values.items():
            setattr(row, name, value)
        row.status = "published"
        row.published_at = row.published_at or now
        row.updated_at = now
    await session.flush()
    await session.execute(
        update(model)
        .where(
            model.destination_id == key["destination_id"],
            model.locale == key["locale"],
            model.slug == key["slug"],
            model.version < key["version"],
            model.status == "published",
        )
        .values(status="retired", updated_at=now)
    )
    return row


async def load_content(
    session: AsyncSession, document: dict[str, Any], now: datetime
) -> SeedResult:
    guides = tours = 0
    touched: set[uuid.UUID] = set()
    for raw in document.get("guides", []):
        sections = _SECTIONS.validate_python(raw["sections"])
        key = {
            "destination_id": await _destination(session, raw["destination"]),
            "locale": raw["locale"],
            "slug": raw["slug"],
            "version": int(raw.get("version", 1)),
        }
        await _publish(
            session,
            DestinationGuide,
            key,
            {
                "title": raw["title"],
                "summary": raw["summary"],
                "content": [s.model_dump(mode="json", exclude_none=True) for s in sections],
                "tier": raw.get("tier", "free"),
                "content_license": raw["content_license"],
                "attribution": raw.get("attribution"),
            },
            now,
        )
        touched.add(key["destination_id"])
        guides += 1
    for raw in document.get("audio_tours", []):
        key = {
            "destination_id": await _destination(session, raw["destination"]),
            "locale": raw["locale"],
            "slug": raw["slug"],
            "version": int(raw.get("version", 1)),
        }
        tour = await _publish(
            session,
            AudioTour,
            key,
            {
                "title": raw["title"],
                "description": raw["description"],
                "tier": raw.get("tier", "free"),
                "content_license": raw["content_license"],
            },
            now,
        )
        await session.execute(delete(AudioTourStop).where(AudioTourStop.tour_id == tour.id))
        session.add_all(
            AudioTourStop(
                tour_id=tour.id,
                sort_order=position,
                place_id=uuid.UUID(stop["place_id"]),
                audio_media_id=uuid.UUID(stop["audio_media_id"]),
                title=stop["title"],
                transcript=stop.get("transcript"),
                trigger_radius_m=int(stop.get("trigger_radius_m", 50)),
                duration_s=int(stop["duration_s"]),
            )
            for position, stop in enumerate(raw["stops"])
        )
        await session.flush()
        tours += 1
    for destination_id in touched:
        published = await session.scalar(
            select(DestinationGuide.id)
            .where(
                DestinationGuide.destination_id == destination_id,
                DestinationGuide.status == "published",
            )
            .limit(1)
        )
        await set_has_guides(session, destination_id, published is not None)
    return SeedResult(guides=guides, audio_tours=tours)


def read_document(path: Path) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


async def _run(path: Path) -> SeedResult:
    # Operator tool: load every module's tables so the foreign keys to products, places and media
    # resolve (the API process imports them all through the composition root).
    import app.models_registry  # noqa: F401

    settings = get_settings()
    database = Database(
        settings.database_url,
        pool_size=1,
        max_overflow=0,
        pool_recycle_seconds=settings.database_pool_recycle_seconds,
        transaction_pooler=settings.database_transaction_pooler,
    )
    try:
        async with database.sessionmaker() as session, session.begin():
            return await load_content(session, read_document(path), SystemClock().now())
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    result = asyncio.run(_run(parser.parse_args().file))
    print(f"guides: {result.guides} published, audio tours: {result.audio_tours}")  # noqa: T201


if __name__ == "__main__":
    main()
