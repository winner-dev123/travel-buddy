"""Editorial launch content (BL-1.23, FEED-001): ``python -m app.modules.social.seeding``.

Creates the Travel Buddy Editors account and its evergreen posts for the launch destinations, so
the feed's destination and global fallbacks have content from day one. Idempotent: post IDs are
derived from the destination and position, so re-running adds only new entries. The posts avoid
prices, opening hours and safety claims, which go stale.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.destinations import service as destinations
from app.modules.identity import service as identity
from app.modules.platform import service as platform
from app.modules.social.domain import clean_body, clean_tags, kind_violations
from app.modules.social.models import Post as PostRow
from app.modules.social.models import PostTag
from app.modules.social.service import _ancestry_or_422, _fan_out

DEFAULT_FILE = Path(__file__).parent / "seed" / "editorial_posts.json"
_NAMESPACE = uuid.UUID("6f1c3c1e-5d0b-4a5e-9a37-3b0f6f0e7a11")


@dataclass(frozen=True, slots=True)
class SeedResult:
    account_created: bool
    created: int
    skipped: int


def post_id(destination: str, index: int) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"{destination}#{index}")


async def load_editorial(session: AsyncSession, document: dict[str, Any]) -> SeedResult:
    account = document["account"]
    author_id = uuid.UUID(account["id"])
    account_created = await identity.ensure_system_account(
        session,
        account_id=author_id,
        handle=account["handle"],
        display_name=account["display_name"],
        bio=account["bio"],
    )
    now = await session.scalar(select(func.now()))
    assert now is not None
    created = skipped = 0
    seen: dict[str, int] = {}
    for position, entry in enumerate(document["posts"]):
        path = entry["destination"]
        index = seen.get(path, 0)
        seen[path] = index + 1
        new_id = post_id(path, index)
        if await session.get(PostRow, new_id) is not None:
            skipped += 1
            continue
        destination_id = await destinations.id_for_path(session, path)
        if destination_id is None:
            raise ValueError(f"unknown destination {path!r}: seed the destinations first")
        body = clean_body(entry["body"])
        problems = kind_violations(
            kind=entry["kind"],
            body=body,
            media_count=0,
            location_precision="destination",
            rating=None,
            trip_id=None,
        )
        if problems:
            raise ValueError(f"{path}#{index}: {problems[0].message}")
        ancestry = await _ancestry_or_422(session, destination_id)
        post = PostRow(
            id=new_id,
            author_id=author_id,
            kind=entry["kind"],
            body=body,
            language="en",
            visibility="public",
            location_precision="destination",
            primary_destination_id=destination_id,
            status="published",
            moderation_state="approved",
            # Spread over the last weeks so the feed's recency signal has something to rank.
            published_at=now - timedelta(hours=6 + position * 11),
        )
        session.add(post)
        await session.flush()
        session.add_all(PostTag(post_id=post.id, tag=tag) for tag in clean_tags(entry["tags"]))
        _fan_out(session, post, ancestry, public=True)
        platform.record_event(
            session,
            aggregate_type="post",
            aggregate_id=post.id,
            event_type="post.published",
            payload={"post_id": str(post.id), "author_id": str(author_id), "public": True},
        )
        created += 1
    await session.flush()
    return SeedResult(account_created=account_created, created=created, skipped=skipped)


def read_document(path: Path = DEFAULT_FILE) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


async def _main(path: Path) -> None:
    from app.core.config import get_settings
    from app.core.db import Database

    settings = get_settings()
    database = Database.from_settings(settings, pool_size=1, max_overflow=0)
    try:
        async with database.sessionmaker() as session, session.begin():
            result = await load_editorial(session, read_document(path))
        print(  # noqa: T201 - CLI output
            f"editorial: account {'created' if result.account_created else 'exists'}, "
            f"{result.created} posts created, {result.skipped} already present"
        )
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Load editorial launch content")
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    args = parser.parse_args()
    asyncio.run(_main(args.file))


if __name__ == "__main__":
    main()
