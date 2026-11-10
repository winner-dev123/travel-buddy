"""Load places into the catalog (BL-4.01; DEST-003).

``python -m app.modules.destinations.place_ingestion --destination portugal/lisbon`` reads the
public places around the destination's centroid from OpenStreetMap (Overpass API, ODbL) and upserts
them. ``--file PATH`` loads a JSON document instead (see ``place_sources.DocumentSource``). Safe to
re-run: places are keyed by ``(provider, provider_place_id)`` and their freshness is refreshed.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import Database
from app.core.errors import AppError, ErrorCode
from app.core.time import Clock, SystemClock
from app.modules.destinations.models import Destination as DestinationRow
from app.modules.destinations.place_sources import DocumentSource, OverpassSource, PlaceSource
from app.modules.destinations.places import IngestResult, ingest
from app.modules.destinations.service import id_for_path

DEFAULT_RADIUS_M = 6000
DEFAULT_LIMIT = 400


async def ingest_destination(
    session: AsyncSession,
    *,
    path: str,
    source: PlaceSource,
    clock: Clock,
    radius_m: int = DEFAULT_RADIUS_M,
    limit: int = DEFAULT_LIMIT,
) -> IngestResult:
    destination_id = await id_for_path(session, path)
    if destination_id is None:
        raise AppError(ErrorCode.NOT_FOUND, f"No active destination at {path!r}.")
    destination = await session.get(DestinationRow, destination_id)
    assert destination is not None
    batch = await source.fetch(
        lat=destination.centroid_lat,
        lng=destination.centroid_lng,
        radius_m=radius_m,
        limit=limit,
    )
    return await ingest(session, destination_id, batch, now=clock.now())


async def _run(args: argparse.Namespace) -> IngestResult:
    settings = get_settings()
    database = Database.from_settings(settings, pool_size=1, max_overflow=0)
    clock = SystemClock()
    try:
        async with httpx.AsyncClient(follow_redirects=False) as http_client:
            source: PlaceSource = (
                DocumentSource.from_file(Path(args.file))
                if args.file
                else OverpassSource(http_client, clock=clock)
            )
            async with database.sessionmaker() as session, session.begin():
                return await ingest_destination(
                    session,
                    path=args.destination,
                    source=source,
                    clock=clock,
                    radius_m=args.radius,
                    limit=args.limit,
                )
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--destination", required=True, help="destination path, e.g. portugal/lisbon"
    )
    parser.add_argument("--file", help="JSON document instead of OpenStreetMap")
    parser.add_argument(
        "--radius", type=int, default=DEFAULT_RADIUS_M, help="metres around the centroid"
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    result = asyncio.run(_run(parser.parse_args()))
    print(f"places: {result.created} created, {result.updated} updated")  # noqa: T201 - CLI output


if __name__ == "__main__":
    main()
