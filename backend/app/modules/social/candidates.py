"""Feed candidate queries and visibility-checked assembly (used by the feed module).

The social module owns post tables, so the feed module asks it for candidates instead of querying
them directly. Candidates carry only what the ranker needs.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.profiles import service as profiles
from app.modules.social.models import Follow, FollowStatus, PostDestination, PostTag, Reaction
from app.modules.social.models import Post as PostRow
from app.modules.social.schemas import Post
from app.modules.social.service import _assemble, _visible

MAX_CANDIDATES = 500


@dataclass(frozen=True, slots=True)
class CandidateQuery:
    viewer_id: uuid.UUID
    since: datetime
    # Destination feeds: posts fanned out to any of these destinations (target + descendants).
    destination_ids: Sequence[uuid.UUID] = ()
    # Posts whose PRIMARY destination is one of these (the target's ancestors, "parent" match).
    parent_destination_ids: Sequence[uuid.UUID] = ()
    # Following tab: posts by these authors (public or followers-only).
    author_ids: Sequence[uuid.UUID] | None = None
    # Global/interest feeds: any publicly listed post (with these tags, if given).
    global_scope: bool = False
    kinds: Sequence[str] = ()
    tags: Sequence[str] = ()
    languages: Sequence[str] = ()
    exclude_post_ids: Sequence[uuid.UUID] = ()
    exclude_author_ids: Sequence[uuid.UUID] = ()
    limit: int = MAX_CANDIDATES


@dataclass(slots=True)
class Candidate:
    post_id: uuid.UUID
    author_id: uuid.UUID
    published_at: datetime
    kind: str
    language: str
    body_length: int
    body_digest: str
    location_precision: str
    primary_destination_id: uuid.UUID | None
    # Depth from the matched destination: 0 exact, >0 descendant; -1 = parent-tagged post.
    match_depth: int | None
    reactions: int
    comments: int
    bookmarks: int
    shares: int
    helpful: int = 0
    tags: list[str] = field(default_factory=list)


def _digest(body: str) -> str:
    normalized = " ".join(body.lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


async def candidates(session: AsyncSession, query: CandidateQuery) -> list[Candidate]:
    """Visible-by-construction candidates: published, not removed, publicly listed (destination
    and global feeds) or followed authors' public/followers posts (following tab)."""
    base = [
        PostRow.status == "published",
        PostRow.moderation_state.in_(("approved", "pending")),
        PostRow.published_at >= query.since,
    ]
    if query.kinds:
        base.append(PostRow.kind.in_(query.kinds))
    if query.languages:
        base.append(
            or_(*(PostRow.language.ilike(f"{lang.split('-')[0]}%") for lang in query.languages))
        )
    if query.exclude_post_ids:
        base.append(PostRow.id.notin_(query.exclude_post_ids))
    if query.exclude_author_ids:
        base.append(PostRow.author_id.notin_(query.exclude_author_ids))
    if query.tags:
        base.append(
            PostRow.id.in_(select(PostTag.post_id).where(PostTag.tag.in_(list(query.tags))))
        )

    rows: list[tuple[PostRow, int | None]] = []
    if query.destination_ids or query.parent_destination_ids:
        exact = (
            select(PostRow, func.min(PostDestination.depth_from_primary))
            .join(PostDestination, PostDestination.post_id == PostRow.id)
            .where(
                *base,
                PostDestination.visibility_public.is_(True),
                PostDestination.destination_id.in_(list(query.destination_ids)),
            )
            .group_by(PostRow.id)
            .order_by(PostRow.published_at.desc())
            .limit(query.limit)
        )
        rows += [(p, depth) for p, depth in (await session.execute(exact)).all()]
        if query.parent_destination_ids:
            parents = (
                select(PostRow)
                .join(PostDestination, PostDestination.post_id == PostRow.id)
                .where(
                    *base,
                    PostDestination.visibility_public.is_(True),
                    PostDestination.is_primary.is_(True),
                    PostDestination.destination_id.in_(list(query.parent_destination_ids)),
                )
                .order_by(PostRow.published_at.desc())
                .limit(query.limit)
            )
            seen = {p.id for p, _ in rows}
            rows += [(p, -1) for p in (await session.scalars(parents)).all() if p.id not in seen]
    elif query.author_ids is not None:
        if not query.author_ids:
            return []
        following = (
            select(PostRow)
            .join(
                Follow,
                and_(
                    Follow.followee_id == PostRow.author_id,
                    Follow.follower_id == query.viewer_id,
                    Follow.status == FollowStatus.ACTIVE,
                ),
            )
            .where(
                *base,
                PostRow.author_id.in_(list(query.author_ids)),
                PostRow.visibility.in_(("public", "followers")),
            )
            .order_by(PostRow.published_at.desc())
            .limit(query.limit)
        )
        rows += [(p, None) for p in (await session.scalars(following)).all()]
    elif query.global_scope:
        public = (
            select(PostRow)
            .where(*base, PostRow.visibility == "public")
            .order_by(PostRow.published_at.desc())
            .limit(query.limit * 2)
        )
        posts = list((await session.scalars(public)).all())
        authors = await profiles.authors(session, list({p.author_id for p in posts}))
        rows += [
            (p, None)
            for p in posts
            if p.author_id in authors and not authors[p.author_id].account_private
        ][: query.limit]

    if not rows:
        return []
    ids = [p.id for p, _ in rows]
    tags: dict[uuid.UUID, list[str]] = {i: [] for i in ids}
    for post_id, tag in (
        await session.execute(select(PostTag.post_id, PostTag.tag).where(PostTag.post_id.in_(ids)))
    ).all():
        tags[post_id].append(str(tag).lower())
    helpful: dict[uuid.UUID, int] = {
        row[0]: row[1]
        for row in (
            await session.execute(
                select(Reaction.post_id, func.count())
                .where(Reaction.post_id.in_(ids), Reaction.reaction == "helpful")
                .group_by(Reaction.post_id)
            )
        ).all()
    }
    result: list[Candidate] = []
    for post, depth in rows:
        assert post.published_at is not None
        result.append(
            Candidate(
                post_id=post.id,
                author_id=post.author_id,
                published_at=post.published_at,
                kind=post.kind,
                language=post.language,
                body_length=len(post.body),
                body_digest=_digest(post.body),
                location_precision=post.location_precision,
                primary_destination_id=post.primary_destination_id,
                match_depth=depth,
                reactions=post.reaction_count,
                comments=post.comment_count,
                bookmarks=post.bookmark_count,
                shares=post.share_count,
                helpful=helpful.get(post.id, 0),
                tags=tags[post.id],
            )
        )
    return result


async def followed_author_ids(session: AsyncSession, viewer_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        (
            await session.scalars(
                select(Follow.followee_id).where(
                    Follow.follower_id == viewer_id, Follow.status == FollowStatus.ACTIVE
                )
            )
        ).all()
    )


async def assemble_visible(
    session: AsyncSession,
    post_ids: Sequence[uuid.UUID],
    viewer_id: uuid.UUID,
    preferences: Sequence[str],
) -> list[Post]:
    """Posts in the given order, re-checked for visibility now (deleted/blocked since the
    snapshot are dropped)."""
    if not post_ids:
        return []
    found = {
        p.id: p
        for p in (
            await session.scalars(select(PostRow).where(PostRow.id.in_(list(post_ids))))
        ).all()
    }
    visible: list[PostRow] = []
    for post_id in post_ids:
        post = found.get(post_id)
        if post is not None and await _visible(session, post, viewer_id):
            visible.append(post)
    return await _assemble(session, visible, viewer_id, preferences)
