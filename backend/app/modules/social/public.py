"""Guest mode: anonymous public posts (AUTH-012, FEED-005, PROF-008).

Only ``public`` + ``approved`` posts by public accounts are served, without viewer fields. The
listing is capped at three pages per cursor chain; guests cannot interact.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode
from app.core.pagination import CursorCodec, Page, PageInfo
from app.modules.destinations import service as destinations
from app.modules.profiles import service as profiles
from app.modules.social.models import Post as PostRow
from app.modules.social.models import PostDestination
from app.modules.social.service import _assemble

MAX_PAGES = 3
CACHE_CONTROL = "public, max-age=60"
_GUEST = uuid.UUID(int=0)  # never an author: assembled posts carry no viewer-specific state
_PUBLIC = and_(
    PostRow.status == "published",
    PostRow.visibility == "public",
    PostRow.moderation_state == "approved",
)


def _public_payload(post: Any) -> dict[str, Any]:
    data: dict[str, Any] = post.as_json()
    data.pop("viewer", None)
    data.pop("moderation_state", None)
    return data


class PublicPostService:
    def __init__(
        self, *, sessionmaker: async_sessionmaker[AsyncSession], cursors: CursorCodec
    ) -> None:
        self._sessionmaker = sessionmaker
        self._cursors = cursors

    async def get(self, post_id: uuid.UUID, *, preferences: Sequence[str]) -> dict[str, Any]:
        async with self._sessionmaker() as session:
            post = await session.scalar(select(PostRow).where(PostRow.id == post_id, _PUBLIC))
            if post is None or not await _author_public(session, post.author_id):
                raise AppError(ErrorCode.NOT_FOUND, "Post not found.")
            [assembled] = await _assemble(session, [post], _GUEST, preferences)
            return _public_payload(assembled)

    async def list(
        self,
        *,
        destination_id: uuid.UUID | None,
        kinds: Sequence[str],
        cursor: str | None,
        limit: int,
        preferences: Sequence[str],
    ) -> Page[dict[str, Any]]:
        scope = f"public.posts.{destination_id}.{','.join(sorted(kinds))}"
        page_number = 0
        after: tuple[datetime, uuid.UUID] | None = None
        if cursor:
            position = self._cursors.decode(cursor, scope=scope)
            page_number = int(position["n"])
            after = (datetime.fromisoformat(str(position["at"])), uuid.UUID(str(position["id"])))
        if page_number >= MAX_PAGES:
            return Page[dict[str, Any]](data=[], page=PageInfo(next_cursor=None, has_more=False))
        async with self._sessionmaker() as session:
            query = select(PostRow).where(_PUBLIC)
            if destination_id is not None:
                if await destinations.ancestry(session, destination_id) is None:
                    raise AppError(ErrorCode.NOT_FOUND, "Destination not found.")
                # visibility_public already excludes private accounts (feed index).
                query = query.join(
                    PostDestination,
                    and_(
                        PostDestination.post_id == PostRow.id,
                        PostDestination.destination_id == destination_id,
                        PostDestination.visibility_public.is_(True),
                    ),
                )
            if kinds:
                query = query.where(PostRow.kind.in_(kinds))
            if after is not None:
                query = query.where(
                    or_(
                        PostRow.published_at < after[0],
                        and_(PostRow.published_at == after[0], PostRow.id < after[1]),
                    )
                )
            # Over-fetch: posts by private accounts are dropped below (global listing).
            rows = list(
                (
                    await session.scalars(
                        query.order_by(PostRow.published_at.desc(), PostRow.id.desc()).limit(
                            limit * 2 + 1
                        )
                    )
                ).all()
            )
            authors = await profiles.authors(session, [r.author_id for r in rows])
            public_rows = [
                r
                for r in rows
                if r.author_id in authors and not authors[r.author_id].account_private
            ]
            page_rows = public_rows[:limit]
            has_more = len(public_rows) > limit or len(rows) > limit * 2
            assembled = await _assemble(session, page_rows, _GUEST, preferences)
        has_more = has_more and page_number + 1 < MAX_PAGES and bool(page_rows)
        next_cursor = None
        if has_more:
            last = page_rows[-1]
            assert last.published_at is not None
            next_cursor = self._cursors.encode(
                {"n": page_number + 1, "at": last.published_at.isoformat(), "id": str(last.id)},
                scope=scope,
            )
        return Page[dict[str, Any]](
            data=[_public_payload(p) for p in assembled],
            page=PageInfo(next_cursor=next_cursor, has_more=has_more),
        )


async def _author_public(session: AsyncSession, author_id: uuid.UUID) -> bool:
    author = (await profiles.authors(session, [author_id])).get(author_id)
    return author is not None and not author.account_private
