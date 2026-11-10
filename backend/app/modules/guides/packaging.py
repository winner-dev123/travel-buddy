"""Build offline packages (BL-4.08; OFF-001).

``python -m app.modules.guides.packaging --destination portugal/lisbon [--locale en ...]`` packages
the destination's published guides, one package per locale (default: every locale with guides),
into private object storage. Unchanged content keeps its published version; changed content becomes
the next version. Needs S3-compatible storage (``MEDIA_STORAGE=s3``): the development store lives in
the API process memory.
"""

from __future__ import annotations

import argparse
import asyncio

import httpx
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import Database
from app.core.time import SystemClock
from app.modules.destinations.service import id_for_path
from app.modules.guides.models import DestinationGuide
from app.modules.guides.packages import build_guide_package
from app.modules.media.service import MediaSettings


async def _run(path: str, locales: list[str]) -> list[str]:
    import app.models_registry  # noqa: F401 - operator tool: every table for the foreign keys
    from app.main import build_media_storage

    settings = get_settings()
    media = MediaSettings()
    if media.resolved_storage != "s3":
        raise SystemExit("offline packages need MEDIA_STORAGE=s3 (shared object storage)")
    database = Database.from_settings(settings, pool_size=1, max_overflow=0)
    clock = SystemClock()
    built: list[str] = []
    try:
        async with httpx.AsyncClient(follow_redirects=False) as http_client:
            storage = build_media_storage(media, http_client, clock)
            assert storage is not None
            async with database.sessionmaker() as session, session.begin():
                destination_id = await id_for_path(session, path)
                if destination_id is None:
                    raise SystemExit(f"unknown destination {path!r}")
                wanted = locales or sorted(
                    set(
                        await session.scalars(
                            select(DestinationGuide.locale).where(
                                DestinationGuide.destination_id == destination_id,
                                DestinationGuide.status == "published",
                            )
                        )
                    )
                )
                for locale in wanted:
                    package = await build_guide_package(
                        session,
                        storage,
                        destination_id=destination_id,
                        locale=locale,
                        now=clock.now(),
                    )
                    if package is not None:
                        built.append(f"{locale}: v{package.version} ({package.total_bytes} bytes)")
    finally:
        await database.dispose()
    return built


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--destination", required=True)
    parser.add_argument("--locale", action="append", default=[])
    args = parser.parse_args()
    for line in asyncio.run(_run(args.destination, args.locale)):
        print(line)  # noqa: T201 - CLI output


if __name__ == "__main__":
    main()
