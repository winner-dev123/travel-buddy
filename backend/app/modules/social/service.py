"""Public interface of the social module: posts (BL-1.10).

* Publishing writes the post, its tags and one ``post_destinations`` row per destination in the
  primary destination's ancestry (Copacabana -> Rio de Janeiro -> Brazil), so destination feeds
  are a single index range scan (LOC-006).
* Location relevance comes from post metadata only, never from the author (POST-003).
* Visibility is enforced on every read; invisible posts are 404 (POST-008).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.pagination import CursorCodec, Page, PageInfo
from app.core.security.principal import Principal
from app.modules.destinations import service as destinations
from app.modules.platform import service as platform
from app.modules.profiles import service as profiles
from app.modules.social.domain import (
    ViewerRelation,
    can_view,
    clean_body,
    clean_tags,
    is_indexable,
    is_publicly_listed,
    kind_violations,
)
from app.modules.social.models import (
    Bookmark,
    Comment,
    Follow,
    FollowStatus,
    PostDestination,
    PostTag,
    Reaction,
)
from app.modules.social.models import Post as PostRow
from app.modules.social.schemas import (
    CreatePostRequest,
    Post,
    PostCounts,
    PostViewerState,
    UpdatePostRequest,
    UserSummary,
)
from app.modules.trust_safety import service as trust_safety

CREATE_ROUTE = "POST /v1/posts"
REFRESH_AUTHOR_VISIBILITY_JOB = "social.refresh_author_visibility"


def _not_found() -> AppError:
    return AppError(ErrorCode.NOT_FOUND, "Post not found.")


def _invalid(field: str, code: str, message: str) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_FAILED,
        message,
        errors=[FieldError(field=field, code=code, message=message)],
    )


def _require_verified_email(principal: Principal) -> None:
    if not principal.email_verified:
        raise AppError(ErrorCode.EMAIL_UNVERIFIED, "Verify your email address before posting.")


async def _relation(
    session: AsyncSession, viewer_id: uuid.UUID, author_id: uuid.UUID
) -> ViewerRelation:
    # Connections (Phase 2) will extend this.
    if viewer_id == author_id:
        return ViewerRelation(is_author=True)
    following = await session.scalar(
        select(Follow.status).where(
            Follow.follower_id == viewer_id,
            Follow.followee_id == author_id,
            Follow.status == FollowStatus.ACTIVE,
        )
    )
    return ViewerRelation(is_author=False, is_follower=following is not None)


async def visible_post(session: AsyncSession, post_id: uuid.UUID, viewer_id: uuid.UUID) -> PostRow:
    """The post if the viewer may see it, else 404 (no existence leak)."""
    post = await session.get(PostRow, post_id)
    if post is None or not await _visible(session, post, viewer_id):
        raise _not_found()
    return post


class PostService:
    def __init__(
        self, *, sessionmaker: async_sessionmaker[AsyncSession], cursors: CursorCodec
    ) -> None:
        self._sessionmaker = sessionmaker
        self._cursors = cursors

    # ─────────────────────────────── create ───────────────────────────────

    async def create(
        self,
        principal: Principal,
        request: CreatePostRequest,
        *,
        idempotency_key: uuid.UUID,
        preferences: Sequence[str],
    ) -> tuple[Post, bool]:
        """Returns ``(post, replayed)``; a replay is the stored original response."""
        _require_verified_email(principal)
        body = clean_body(request.body)
        try:
            tags = clean_tags(list(request.tags))
        except ValueError as exc:
            raise _invalid("/tags", "invalid", str(exc)) from exc
        _check_references(request.media_ids, request.trip_id, request.place_id)
        _check_location_fields(request.location_precision, request.destination_id, request.place_id)
        problems = kind_violations(
            kind=request.kind,
            body=body,
            media_count=len(request.media_ids),
            location_precision=request.location_precision,
            rating=request.rating,
            trip_id=request.trip_id,
        )
        if problems:
            raise AppError(
                ErrorCode.VALIDATION_FAILED,
                problems[0].message,
                errors=[
                    FieldError(field=p.field, code=p.code, message=p.message) for p in problems
                ],
            )
        async with self._sessionmaker() as session, session.begin():
            replay = await platform.idempotency.claim(
                session,
                user_id=principal.user_id,
                key=idempotency_key,
                route=CREATE_ROUTE,
                payload=request.model_dump(mode="json"),
            )
            if replay is not None:
                return Post.model_validate(replay.body), True
            await trust_safety.ensure_not_restricted(
                session,
                principal.user_id,
                "posting_limited",
                message="Posting is limited on your account right now.",
            )
            ancestry = await _ancestry_or_422(session, request.destination_id)
            author = (await profiles.authors(session, [principal.user_id]))[principal.user_id]
            now = await session.scalar(select(func.now()))
            post = PostRow(
                author_id=principal.user_id,
                kind=request.kind,
                body=body,
                language=request.language or author.ui_locale,
                visibility=request.visibility,
                location_precision=request.location_precision,
                primary_destination_id=request.destination_id,
                travel_date=request.travel_date,
                rating=request.rating,
                status="published",
                moderation_state="approved",  # post-moderation: reports trigger review (BL-1.14)
                published_at=now,
            )
            session.add(post)
            await session.flush()
            session.add_all(PostTag(post_id=post.id, tag=tag) for tag in tags)
            public = is_publicly_listed(
                visibility=post.visibility,
                moderation_state=post.moderation_state,
                account_private=author.account_private,
            )
            _fan_out(session, post, ancestry, public=public)
            await session.flush()
            platform.record_event(
                session,
                aggregate_type="post",
                aggregate_id=post.id,
                event_type="post.published",
                payload={
                    "post_id": str(post.id),
                    "author_id": str(post.author_id),
                    "public": public,
                },
            )
            [response] = await _assemble(session, [post], principal.user_id, preferences)
            await platform.idempotency.complete(
                session,
                user_id=principal.user_id,
                key=idempotency_key,
                status=201,
                body=response.as_json(),
            )
        return response, False

    # ─────────────────────────────── read ───────────────────────────────

    async def get(
        self, viewer_id: uuid.UUID, post_id: uuid.UUID, *, preferences: Sequence[str]
    ) -> Post:
        async with self._sessionmaker() as session:
            post = await session.get(PostRow, post_id)
            if post is None or not await _visible(session, post, viewer_id):
                raise _not_found()
            [response] = await _assemble(session, [post], viewer_id, preferences)
            return response

    async def list_by_author(
        self,
        viewer_id: uuid.UUID,
        author_id: uuid.UUID,
        *,
        cursor: str | None,
        limit: int,
        preferences: Sequence[str],
    ) -> Page[Post]:
        scope = f"posts.author.{author_id}"
        async with self._sessionmaker() as session:
            author = (await profiles.authors(session, [author_id])).get(author_id)
            if author is None or await trust_safety.is_blocked(session, viewer_id, author_id):
                raise AppError(ErrorCode.NOT_FOUND, "User not found.")
            relation = await _relation(session, viewer_id, author_id)
            query = select(PostRow).where(
                PostRow.author_id == author_id, PostRow.status == "published"
            )
            if not relation.is_author:
                allowed = ["followers"] if relation.is_follower else []
                if relation.is_connected:
                    allowed.append("connections")
                if not author.account_private or relation.is_follower:
                    allowed.append("public")
                query = query.where(
                    PostRow.moderation_state != "removed", PostRow.visibility.in_(allowed)
                )
            if cursor:
                position = self._cursors.decode(cursor, scope=scope)
                after_at = datetime.fromisoformat(str(position["at"]))
                after_id = uuid.UUID(str(position["id"]))
                query = query.where(
                    or_(
                        PostRow.published_at < after_at,
                        and_(PostRow.published_at == after_at, PostRow.id < after_id),
                    )
                )
            rows = list(
                (
                    await session.scalars(
                        query.order_by(PostRow.published_at.desc(), PostRow.id.desc()).limit(
                            limit + 1
                        )
                    )
                ).all()
            )
            has_more = len(rows) > limit
            rows = rows[:limit]
            data = await _assemble(session, rows, viewer_id, preferences)
        next_cursor = None
        if has_more and rows and rows[-1].published_at is not None:
            next_cursor = self._cursors.encode(
                {"at": rows[-1].published_at.isoformat(), "id": str(rows[-1].id)}, scope=scope
            )
        return Page[Post](data=data, page=PageInfo(next_cursor=next_cursor, has_more=has_more))

    # ─────────────────────────────── edit / delete ───────────────────────────────

    async def update(
        self,
        principal: Principal,
        post_id: uuid.UUID,
        request: UpdatePostRequest,
        *,
        preferences: Sequence[str],
    ) -> Post:
        changes = request.changes()
        async with self._sessionmaker() as session, session.begin():
            post = await session.get(PostRow, post_id, with_for_update=True)
            if post is None or post.author_id != principal.user_id or post.status != "published":
                raise _not_found()
            if post.moderation_state == "removed":
                raise AppError(ErrorCode.FORBIDDEN, "Posts removed by moderation can't be edited.")
            author = (await profiles.authors(session, [post.author_id]))[post.author_id]
            was_public = is_publicly_listed(
                visibility=post.visibility,
                moderation_state=post.moderation_state,
                account_private=author.account_private,
            )
            if "body" in changes:
                post.body = clean_body(changes["body"])
            for field in ("visibility", "travel_date", "rating"):
                if field in changes:
                    setattr(post, field, changes[field])
            location_changed = bool(
                {"location_precision", "destination_id", "place_id"} & set(changes)
            )
            if location_changed:
                precision = changes.get("location_precision", post.location_precision)
                destination_id = changes.get("destination_id", post.primary_destination_id)
                if precision == "none":
                    destination_id = None
                _check_references([], None, changes.get("place_id"))
                _check_location_fields(precision, destination_id, None)
                post.location_precision = precision
                post.primary_destination_id = destination_id
            problems = kind_violations(
                kind=post.kind,
                body=post.body,
                media_count=0,
                location_precision=post.location_precision,
                rating=post.rating,
                trip_id=post.trip_id,
            )
            if problems:
                raise AppError(
                    ErrorCode.VALIDATION_FAILED,
                    problems[0].message,
                    errors=[
                        FieldError(field=p.field, code=p.code, message=p.message) for p in problems
                    ],
                )
            if "tags" in changes:
                try:
                    tags = clean_tags(changes["tags"])
                except ValueError as exc:
                    raise _invalid("/tags", "invalid", str(exc)) from exc
                await session.execute(delete(PostTag).where(PostTag.post_id == post.id))
                session.add_all(PostTag(post_id=post.id, tag=tag) for tag in tags)
            post.edited_at = func.now()
            is_public = is_publicly_listed(
                visibility=post.visibility,
                moderation_state=post.moderation_state,
                account_private=author.account_private,
            )
            if location_changed:
                ancestry = await _ancestry_or_422(session, post.primary_destination_id)
                await session.execute(
                    delete(PostDestination).where(PostDestination.post_id == post.id)
                )
                _fan_out(session, post, ancestry, public=is_public)
            elif is_public != was_public:
                await session.execute(
                    update(PostDestination)
                    .where(PostDestination.post_id == post.id)
                    .values(visibility_public=is_public)
                )
            await session.flush()
            await session.refresh(post)
            platform.record_event(
                session,
                aggregate_type="post",
                aggregate_id=post.id,
                event_type="post.updated",
                payload={
                    "post_id": str(post.id),
                    "author_id": str(post.author_id),
                    "changed": sorted(changes),
                    "was_public": was_public,
                    "public": is_public,
                },
            )
            [response] = await _assemble(session, [post], principal.user_id, preferences)
            return response

    async def delete(self, principal: Principal, post_id: uuid.UUID) -> None:
        """Tombstone now (gone from every feed and read); hard delete after 30 days (BL-1.18)."""
        async with self._sessionmaker() as session, session.begin():
            post = await session.get(PostRow, post_id, with_for_update=True)
            if post is None or post.author_id != principal.user_id or post.status != "published":
                raise _not_found()
            was_public = bool(
                await session.scalar(
                    select(func.bool_or(PostDestination.visibility_public)).where(
                        PostDestination.post_id == post.id
                    )
                )
            )
            post.status = "deleted"
            post.deleted_at = func.now()
            await session.execute(delete(PostDestination).where(PostDestination.post_id == post.id))
            platform.record_event(
                session,
                aggregate_type="post",
                aggregate_id=post.id,
                event_type="post.deleted",
                payload={
                    "post_id": str(post.id),
                    "author_id": str(post.author_id),
                    "was_public": was_public,
                },
            )


# ─────────────────────────────── jobs ───────────────────────────────


async def refresh_author_visibility(session: AsyncSession, author_id: uuid.UUID) -> int:
    """Recompute feed visibility after an account turns private/public (PROF-004). Going public
    also approves pending follow requests, which no longer need approval."""
    author = (await profiles.authors(session, [author_id])).get(author_id)
    if author is None:
        return 0
    if not author.account_private:
        await session.execute(
            update(Follow)
            .where(Follow.followee_id == author_id, Follow.status == FollowStatus.PENDING)
            .values(status=FollowStatus.ACTIVE)
        )
    posts = (
        await session.scalars(
            select(PostRow).where(PostRow.author_id == author_id, PostRow.status == "published")
        )
    ).all()
    for post in posts:
        public = is_publicly_listed(
            visibility=post.visibility,
            moderation_state=post.moderation_state,
            account_private=author.account_private,
        )
        await session.execute(
            update(PostDestination)
            .where(PostDestination.post_id == post.id, PostDestination.visibility_public != public)
            .values(visibility_public=public)
        )
    return len(posts)


# ─────────────────────────────── helpers ───────────────────────────────


def _check_references(
    media_ids: Sequence[uuid.UUID], trip_id: uuid.UUID | None, place_id: uuid.UUID | None
) -> None:
    # These modules are not built yet (media BL-1.08, trips, places Phase 4): nothing can match.
    if media_ids:
        raise _invalid("/media_ids", "not_found", "Media not found.")
    if trip_id is not None:
        raise _invalid("/trip_id", "not_found", "Trip not found.")
    if place_id is not None:
        raise _invalid("/place_id", "not_found", "Place not found.")


def _check_location_fields(
    precision: str, destination_id: uuid.UUID | None, place_id: uuid.UUID | None
) -> None:
    if precision == "none" and (destination_id is not None or place_id is not None):
        raise _invalid(
            "/location_precision", "inconsistent", "Remove the destination for 'no location'."
        )
    if precision == "destination" and destination_id is None:
        raise _invalid("/destination_id", "required", "Choose a destination.")
    if precision == "place" and place_id is None:
        raise _invalid("/place_id", "required", "Choose a place.")


async def _ancestry_or_422(
    session: AsyncSession, destination_id: uuid.UUID | None
) -> list[uuid.UUID]:
    if destination_id is None:
        return []
    ancestry = await destinations.ancestry(session, destination_id)
    if ancestry is None:
        raise _invalid("/destination_id", "not_found", "Destination not found.")
    return ancestry


def _fan_out(
    session: AsyncSession, post: PostRow, ancestry: list[uuid.UUID], *, public: bool
) -> None:
    """One row per destination from the primary up to the country."""
    assert post.published_at is not None
    for depth, destination_id in enumerate(reversed(ancestry)):
        session.add(
            PostDestination(
                post_id=post.id,
                destination_id=destination_id,
                is_primary=depth == 0,
                depth_from_primary=depth,
                published_at=post.published_at,
                visibility_public=public,
            )
        )


async def _visible(session: AsyncSession, post: PostRow, viewer_id: uuid.UUID) -> bool:
    author = (await profiles.authors(session, [post.author_id])).get(post.author_id)
    if author is None:
        return False
    if viewer_id != post.author_id and await trust_safety.is_blocked(
        session, viewer_id, post.author_id
    ):
        return False  # blocks hide content in both directions (SAFE-001)
    return can_view(
        visibility=post.visibility,
        status=post.status,
        moderation_state=post.moderation_state,
        account_private=author.account_private,
        relation=await _relation(session, viewer_id, post.author_id),
    )


async def _assemble(
    session: AsyncSession,
    posts: Sequence[PostRow],
    viewer_id: uuid.UUID,
    preferences: Sequence[str],
) -> list[Post]:
    if not posts:
        return []
    ids = [p.id for p in posts]
    authors = await profiles.authors(session, [p.author_id for p in posts])
    summaries = await destinations.summaries_by_id(
        session, [p.primary_destination_id for p in posts if p.primary_destination_id], preferences
    )
    reactions_by_type: dict[uuid.UUID, dict[str, int]] = {i: {} for i in ids}
    for post_id, reaction, count in (
        await session.execute(
            select(Reaction.post_id, Reaction.reaction, func.count())
            .where(Reaction.post_id.in_(ids))
            .group_by(Reaction.post_id, Reaction.reaction)
        )
    ).all():
        reactions_by_type[post_id][reaction] = count
    mine: dict[uuid.UUID, str] = {
        row.post_id: row.reaction
        for row in (
            await session.execute(
                select(Reaction.post_id, Reaction.reaction).where(
                    Reaction.post_id.in_(ids), Reaction.user_id == viewer_id
                )
            )
        ).all()
    }
    bookmarked = set(
        (
            await session.scalars(
                select(Bookmark.post_id).where(
                    Bookmark.post_id.in_(ids), Bookmark.user_id == viewer_id
                )
            )
        ).all()
    )
    tags: dict[uuid.UUID, list[str]] = {i: [] for i in ids}
    for post_id, tag in (
        await session.execute(
            select(PostTag.post_id, PostTag.tag)
            .where(PostTag.post_id.in_(ids))
            .order_by(PostTag.tag)
        )
    ).all():
        tags[post_id].append(tag)
    result: list[Post] = []
    for post in posts:
        author = authors[post.author_id]
        is_author = post.author_id == viewer_id
        payload: dict[str, Any] = {
            "id": post.id,
            "author": UserSummary(
                id=author.id, handle=author.handle, display_name=author.display_name
            ),
            "kind": post.kind,
            "body": post.body,
            "language": post.language,
            "visibility": post.visibility,
            "location_precision": post.location_precision,
            "primary_destination": (
                summaries.get(post.primary_destination_id) if post.primary_destination_id else None
            ),
            "travel_date": post.travel_date,
            "rating": post.rating,
            "trip_id": post.trip_id,
            "tags": tags[post.id],
            "published_at": post.published_at,
            "edited_at": post.edited_at,
            "counts": PostCounts.model_validate(
                {
                    "reactions": post.reaction_count,
                    "comments": post.comment_count,
                    "bookmarks": post.bookmark_count,
                    "shares": post.share_count,
                    "reactions_by_type": reactions_by_type[post.id],
                }
            ),
            "indexable": is_indexable(
                visibility=post.visibility,
                moderation_state=post.moderation_state,
                account_private=author.account_private,
                author_opted_in=author.search_engine_indexing,
            ),
            "viewer": PostViewerState.model_validate(
                {
                    "reaction": mine.get(post.id),
                    "bookmarked": post.id in bookmarked,
                    "is_author": is_author,
                    "can_edit": is_author and post.moderation_state != "removed",
                    "can_delete": is_author,
                    "can_comment": post.moderation_state != "removed",
                }
            ),
            "moderation_state": post.moderation_state if is_author else None,
        }
        result.append(Post.model_validate(payload))
    return result


def subscribe(router: platform.EventRouter) -> None:
    """React to profile changes that alter who may see an author's posts."""
    router.subscribe(
        "profile.updated",
        queue="default",
        kind=REFRESH_AUTHOR_VISIBILITY_JOB,
        when=lambda data: "account_visibility" in (data.get("changed") or []),
    )


def make_handlers(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> dict[str, platform.JobHandler]:
    async def refresh(job: platform.Job) -> None:
        data = job.payload.get("data") or {}
        async with sessionmaker() as session, session.begin():
            await refresh_author_visibility(session, uuid.UUID(str(data["user_id"])))

    return {REFRESH_AUTHOR_VISIBILITY_JOB: refresh}


async def remove_follows_between(session: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> None:
    """Block hook: follows and follow requests end in both directions (SAFE-001)."""
    await session.execute(
        delete(Follow).where(
            or_(
                and_(Follow.follower_id == a, Follow.followee_id == b),
                and_(Follow.follower_id == b, Follow.followee_id == a),
            )
        )
    )


# Feed-facing queries live in candidates.py (they need the helpers above); re-exported here because
# other modules may import only ``social.service``.
from app.modules.social.candidates import (  # noqa: E402
    Candidate as Candidate,
)
from app.modules.social.candidates import (  # noqa: E402
    CandidateQuery as CandidateQuery,
)
from app.modules.social.candidates import (  # noqa: E402
    assemble_visible as assemble_visible,
)
from app.modules.social.candidates import (  # noqa: E402
    candidates as candidates,
)
from app.modules.social.candidates import (  # noqa: E402
    followed_author_ids as followed_author_ids,
)

# ─────────────────────────────── moderation hooks (BL-1.14) ───────────────────────────────


async def post_evidence(
    session: AsyncSession, post_id: uuid.UUID, reporter_id: uuid.UUID
) -> tuple[uuid.UUID, dict[str, Any]] | None:
    """(author, snapshot) of a post the reporter can see, else None."""
    post = await session.get(PostRow, post_id)
    if post is None or not await _visible(session, post, reporter_id):
        return None
    tags = list(
        (await session.scalars(select(PostTag.tag).where(PostTag.post_id == post.id))).all()
    )
    return post.author_id, {
        "kind": post.kind,
        "body": post.body,
        "language": post.language,
        "visibility": post.visibility,
        "tags": [str(t) for t in tags],
        "primary_destination_id": str(post.primary_destination_id)
        if post.primary_destination_id
        else None,
        "published_at": post.published_at.isoformat() if post.published_at else None,
    }


async def comment_evidence(
    session: AsyncSession, comment_id: uuid.UUID, reporter_id: uuid.UUID
) -> tuple[uuid.UUID, dict[str, Any]] | None:
    comment = await session.get(Comment, comment_id)
    if comment is None or comment.deleted_at is not None:
        return None
    post = await session.get(PostRow, comment.post_id)
    if post is None or not await _visible(session, post, reporter_id):
        return None
    return comment.author_id, {
        "body": comment.body,
        "post_id": str(comment.post_id),
        "parent_comment_id": str(comment.parent_comment_id) if comment.parent_comment_id else None,
        "created_at": comment.created_at.isoformat(),
    }


async def moderate_content(
    session: AsyncSession, target_type: str, target_id: uuid.UUID, state: str
) -> uuid.UUID:
    """Set ``moderation_state`` on a post or comment (remove / restore / limit, ADM-002).
    Returns the content author's ID. Feed visibility and the web cache follow."""
    if target_type == "comment":
        comment = await session.get(Comment, target_id, with_for_update=True)
        if comment is None:
            raise _not_found()
        comment.moderation_state = state
        return comment.author_id
    post = await session.get(PostRow, target_id, with_for_update=True)
    if post is None or post.status == "deleted":
        raise _not_found()
    author = (await profiles.authors(session, [post.author_id]))[post.author_id]
    was_public = is_publicly_listed(
        visibility=post.visibility,
        moderation_state=post.moderation_state,
        account_private=author.account_private,
    )
    post.moderation_state = state
    public = is_publicly_listed(
        visibility=post.visibility, moderation_state=state, account_private=author.account_private
    )
    await session.execute(
        update(PostDestination)
        .where(PostDestination.post_id == post.id)
        .values(visibility_public=public)
    )
    platform.record_event(
        session,
        aggregate_type="post",
        aggregate_id=post.id,
        event_type="post.moderated",
        payload={
            "post_id": str(post.id),
            "state": state,
            "was_public": was_public,
            "public": public,
        },
    )
    return post.author_id
