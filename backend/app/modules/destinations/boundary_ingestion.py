"""Load licensed destination boundaries from OpenStreetMap (DEST-005, ADR-0027).

``python -m app.modules.destinations.boundary_ingestion --destination germany/berlin
--relation 62422`` replaces the destination's approximate bounding box with the polygon of that
OSM boundary relation. ``--all`` does it for every launch destination whose seed entry names an
``osm_relation_id``. PostGIS is required. Safe to re-run; re-seeding the catalog keeps these
polygons.
"""

from __future__ import annotations

import argparse
import asyncio

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import Database
from app.core.errors import AppError, ErrorCode
from app.modules.destinations.boundaries import (
    OSM_SOURCE_PREFIX,
    OverpassBoundarySource,
    store_boundary,
)
from app.modules.destinations.seeding import read_document
from app.modules.destinations.service import id_for_path

# Overpass asks clients to pace themselves; one relation every few seconds is plenty.
PAUSE_SECONDS = 5.0


async def load_relation(
    session: AsyncSession, source: OverpassBoundarySource, *, path: str, relation_id: int
) -> None:
    destination_id = await id_for_path(session, path)
    if destination_id is None:
        raise AppError(ErrorCode.NOT_FOUND, f"No active destination at {path!r}.")
    wkt = await source.fetch(relation_id)
    await store_boundary(session, destination_id, wkt, source=f"{OSM_SOURCE_PREFIX}{relation_id}")


def seeded_relations() -> list[tuple[str, int]]:
    """``(path, relation id)`` for the launch destinations that name one."""
    return [
        (entry["path"], int(entry["osm_relation_id"]))
        for entry in read_document()["destinations"]
        if entry.get("osm_relation_id")
    ]


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    database = Database(
        settings.database_url,
        pool_size=1,
        max_overflow=0,
        pool_recycle_seconds=settings.database_pool_recycle_seconds,
        transaction_pooler=settings.database_transaction_pooler,
    )
    targets = seeded_relations() if args.all else [(args.destination, args.relation)]
    loaded = 0
    try:
        async with httpx.AsyncClient(follow_redirects=False) as http_client:
            source = OverpassBoundarySource(http_client)
            for index, (path, relation_id) in enumerate(targets):
                if index:
                    await asyncio.sleep(PAUSE_SECONDS)
                async with database.sessionmaker() as session, session.begin():
                    await load_relation(session, source, path=path, relation_id=relation_id)
                loaded += 1
                print(f"{path}: osm relation {relation_id}")  # noqa: T201 - CLI output
    finally:
        await database.dispose()
    return loaded


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--destination", help="destination path, e.g. germany/berlin")
    target.add_argument(
        "--all", action="store_true", help="every seed entry with an osm_relation_id"
    )
    parser.add_argument("--relation", type=int, help="OSM relation id (with --destination)")
    args = parser.parse_args()
    if args.destination and not args.relation:
        parser.error("--destination needs --relation")
    loaded = asyncio.run(_run(args))
    print(f"boundaries: {loaded} loaded")  # noqa: T201 - CLI output


if __name__ == "__main__":
    main()
