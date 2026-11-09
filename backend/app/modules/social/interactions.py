"""Reactions, bookmarks, shares and comments (BL-1.11, POST-005).

Every interaction first checks that the viewer may see the post (404 otherwise). Counters are
updated with atomic SQL increments in the same transaction as the row change.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.pagination import CursorCodec, Page, PageInfo
from app.core.security.principal import Principal
from app.modules.platform import service as platform
from app.modules.profiles import service as profiles
from app.modules.social.domain import clean_body, is_publicly_listed
from app.modules.social.models import Bookmark, Comment, Reaction
from app.modules.social.models import Post as PostRow
from app.modules.social.schemas import (
    CommentOut,
    CommentViewer,
    CreateCommentRequest,
    Post,
    PostCounts,
    ReactionOut,
    ReactionResult,
    ShareLink,
    UserSummary,
)
from app.modules.social.service import _assemble, _require_verified_email, visible_post
from app.modules.trust_safety import service as trust_safety

COMMENT_ROUTE = "POST /v1/posts/{postId}/comments"


def _comment_not_found() -> AppError:
    return AppError(ErrorCode.NOT_FOUND, "Comment not found.")


async def _counts(session: AsyncSession, post_id: uuid.UUID) -> PostCounts:
    post = await session.get(PostRow, post_id, populate_existing=True)
    assert post is not None
    by_type: dict[str, int] = {
        row[0]: row[1]
        for row in (
            await session.execute(
                select(Reaction.reaction, func.count())
                .where(Reaction.post_id == post_id)
                .group_by(Reaction.reaction)
            )
        ).all()
    }
    return PostCounts.model_validate(
        {
            "reactions": post.reaction_count,
            "comments": post.comment_count,
            "bookmarks": post.bookmark_count,
            "shares": post.share_count,
            "reactions_by_type": by_type,
        }
    )


class InteractionService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        cursors: CursorCodec,
        public_site_url: str,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._cursors = cursors
        self._site = public_site_url.rstrip("/")

    # ─────────────────────────────── reactions ───────────────────────────────

    async def react(
        self, viewer_id: uuid.UUID, post_id: uuid.UUID, reaction: str
    ) -> ReactionResult:
        """Idempotent upsert: the same reaction is a no-op, a different one replaces it."""
        async with self._sessionmaker() as session, session.begin():
            await visible_post(session, post_id, viewer_id)
            inserted = await session.execute(
                insert(Reaction)
                .values(post_id=post_id, user_id=viewer_id, reaction=reaction)
                .on_conflict_do_update(
                    index_elements=[Reaction.post_id, Reaction.user_id],
                    set_={"reaction": reaction},
                )
                .returning(Reaction.created_at == func.now())  # true only for a new row
            )
            if inserted.scalar_one():
                await session.execute(
                    update(PostRow)
                    .where(PostRow.id == post_id)
                    .values(reaction_count=PostRow.reaction_count + 1)
                )
                platform.record_event(
                    session,
                    aggregate_type="post",
                    aggregate_id=post_id,
                    event_type="post.reacted",
                    payload={
                        "post_id": str(post_id),
                        "user_id": str(viewer_id),
                        "reaction": reaction,
                    },
                )
            return ReactionResult.model_validate(
                {"reaction": reaction, "counts": await _counts(session, post_id)}
            )

    async def unreact(self, viewer_id: uuid.UUID, post_id: uuid.UUID) -> None:
        async with self._sessionmaker() as session, session.begin():
            await visible_post(session, post_id, viewer_id)
            removed = await session.execute(
                delete(Reaction)
                .where(Reaction.post_id == post_id, Reaction.user_id == viewer_id)
                .returning(Reaction.post_id)
            )
            if removed.first() is not None:
                await session.execute(
                    update(PostRow)
                    .where(PostRow.id == post_id)
                    .values(reaction_count=func.greatest(PostRow.reaction_count - 1, 0))
                )

    async def list_reactions(
        self, viewer_id: uuid.UUID, post_id: uuid.UUID, *, cursor: str | None, limit: int
    ) -> Page[ReactionOut]:
        scope = f"reactions.{post_id}"
        async with self._sessionmaker() as session:
            await visible_post(session, post_id, viewer_id)
            hidden = await trust_safety.blocked_ids(session, viewer_id)
            query = select(Reaction).where(Reaction.post_id == post_id)
            if hidden:
                query = query.where(Reaction.user_id.notin_(hidden))
            if cursor:
                at, user = _position(self._cursors.decode(cursor, scope=scope))
                query = query.where(
                    or_(
                        Reaction.created_at < at,
                        and_(Reaction.created_at == at, Reaction.user_id < user),
                    )
                )
            rows = list(
                (
                    await session.scalars(
                        query.order_by(Reaction.created_at.desc(), Reaction.user_id.desc()).limit(
                            limit + 1
                        )
                    )
                ).all()
            )
            has_more = len(rows) > limit
            rows = rows[:limit]
            users = await profiles.authors(session, [r.user_id for r in rows])
        data = [
            ReactionOut(user=_user(users[r.user_id]), reaction=r.reaction, created_at=r.created_at)  # type: ignore[arg-type]
            for r in rows
            if r.user_id in users
        ]
        next_cursor = (
            self._cursors.encode(
                {"at": rows[-1].created_at.isoformat(), "id": str(rows[-1].user_id)}, scope=scope
            )
            if has_more and rows
            else None
        )
        return Page[ReactionOut](
            data=data, page=PageInfo(next_cursor=next_cursor, has_more=has_more)
        )

    # ─────────────────────────────── bookmarks ───────────────────────────────

    async def bookmark(self, viewer_id: uuid.UUID, post_id: uuid.UUID) -> None:
        async with self._sessionmaker() as session, session.begin():
            await visible_post(session, post_id, viewer_id)
            inserted = await session.execute(
                insert(Bookmark)
                .values(user_id=viewer_id, post_id=post_id)
                .on_conflict_do_nothing()
                .returning(Bookmark.post_id)
            )
            if inserted.first() is not None:
                await session.execute(
                    update(PostRow)
                    .where(PostRow.id == post_id)
                    .values(bookmark_count=PostRow.bookmark_count + 1)
                )

    async def unbookmark(self, viewer_id: uuid.UUID, post_id: uuid.UUID) -> None:
        """Idempotent; works even if the post is no longer visible (a bookmark is the viewer's)."""
        async with self._sessionmaker() as session, session.begin():
            removed = await session.execute(
                delete(Bookmark)
                .where(Bookmark.user_id == viewer_id, Bookmark.post_id == post_id)
                .returning(Bookmark.post_id)
            )
            if removed.first() is not None:
                await session.execute(
                    update(PostRow)
                    .where(PostRow.id == post_id)
                    .values(bookmark_count=func.greatest(PostRow.bookmark_count - 1, 0))
                )

    async def list_bookmarks(
        self,
        viewer_id: uuid.UUID,
        *,
        cursor: str | None,
        limit: int,
        preferences: Sequence[str],
    ) -> Page[Post]:
        """My bookmarks, newest first; posts I can no longer see are skipped."""
        scope = "bookmarks"
        async with self._sessionmaker() as session:
            query = (
                select(Bookmark, PostRow)
                .join(PostRow, PostRow.id == Bookmark.post_id)
                .where(Bookmark.user_id == viewer_id, PostRow.status == "published")
            )
            if cursor:
                at, post = _position(self._cursors.decode(cursor, scope=scope))
                query = query.where(
                    or_(
                        Bookmark.created_at < at,
                        and_(Bookmark.created_at == at, Bookmark.post_id < post),
                    )
                )
            rows = (
                await session.execute(
                    query.order_by(Bookmark.created_at.desc(), Bookmark.post_id.desc()).limit(
                        limit + 1
                    )
                )
            ).all()
            has_more = len(rows) > limit
            rows = rows[:limit]
            visible: list[PostRow] = []
            for _, post_row in rows:
                try:
                    visible.append(await visible_post(session, post_row.id, viewer_id))
                except AppError:
                    continue
            data = await _assemble(session, visible, viewer_id, preferences)
        next_cursor = None
        if has_more and rows:
            last = rows[-1][0]
            next_cursor = self._cursors.encode(
                {"at": last.created_at.isoformat(), "id": str(last.post_id)}, scope=scope
            )
        return Page[Post](data=data, page=PageInfo(next_cursor=next_cursor, has_more=has_more))

    # ─────────────────────────────── shares ───────────────────────────────

    async def share(
        self, viewer_id: uuid.UUID, post_id: uuid.UUID, channel: str | None
    ) -> ShareLink:
        """Only posts everyone can see may be shared externally (guest preview)."""
        async with self._sessionmaker() as session, session.begin():
            post = await visible_post(session, post_id, viewer_id)
            author = (await profiles.authors(session, [post.author_id]))[post.author_id]
            if not is_publicly_listed(
                visibility=post.visibility,
                moderation_state=post.moderation_state,
                account_private=author.account_private,
            ):
                raise AppError(
                    ErrorCode.FORBIDDEN, "Only public posts can be shared outside the app."
                )
            await session.execute(
                update(PostRow)
                .where(PostRow.id == post_id)
                .values(share_count=PostRow.share_count + 1)
            )
            platform.record_event(
                session,
                aggregate_type="post",
                aggregate_id=post_id,
                event_type="post.shared",
                payload={"post_id": str(post_id), "channel": channel or "unknown"},
            )
        return ShareLink(url=f"{self._site}/stories/{post_id}")

    # ─────────────────────────────── comments ───────────────────────────────

    async def create_comment(
        self,
        principal: Principal,
        post_id: uuid.UUID,
        request: CreateCommentRequest,
        *,
        idempotency_key: uuid.UUID,
    ) -> tuple[CommentOut, bool]:
        _require_verified_email(principal)
        body = clean_body(request.body)
        if not body:
            raise AppError(
                ErrorCode.VALIDATION_FAILED,
                "Write something.",
                errors=[FieldError(field="/body", code="required", message="Write something.")],
            )
        async with self._sessionmaker() as session, session.begin():
            replay = await platform.idempotency.claim(
                session,
                user_id=principal.user_id,
                key=idempotency_key,
                route=COMMENT_ROUTE,
                payload={"post_id": str(post_id), **request.model_dump(mode="json")},
            )
            if replay is not None:
                return CommentOut.model_validate(replay.body), True
            post = await visible_post(session, post_id, principal.user_id)
            if post.moderation_state == "removed":
                raise AppError(ErrorCode.FORBIDDEN, "Comments are closed on this post.")
            if request.parent_comment_id is not None:
                parent = await session.get(Comment, request.parent_comment_id, with_for_update=True)
                if (
                    parent is None
                    or parent.post_id != post_id
                    or parent.parent_comment_id is not None
                    or parent.deleted_at is not None
                ):
                    raise AppError(
                        ErrorCode.VALIDATION_FAILED,
                        "You can only reply to a top-level comment on this post.",
                        errors=[
                            FieldError(
                                field="/parent_comment_id",
                                code="invalid",
                                message="Not a top-level comment on this post.",
                            )
                        ],
                    )
                parent.reply_count += 1
            author = (await profiles.authors(session, [principal.user_id]))[principal.user_id]
            comment = Comment(
                post_id=post_id,
                author_id=principal.user_id,
                parent_comment_id=request.parent_comment_id,
                body=body,
                language=author.ui_locale,
            )
            session.add(comment)
            await session.execute(
                update(PostRow)
                .where(PostRow.id == post_id)
                .values(comment_count=PostRow.comment_count + 1)
            )
            await session.flush()
            await session.refresh(comment)
            platform.record_event(
                session,
                aggregate_type="post",
                aggregate_id=post_id,
                event_type="post.commented",
                payload={
                    "post_id": str(post_id),
                    "comment_id": str(comment.id),
                    "author_id": str(principal.user_id),
                    "post_author_id": str(post.author_id),
                },
            )
            [out] = await _comments(session, [comment], principal.user_id, post.author_id)
            await platform.idempotency.complete(
                session,
                user_id=principal.user_id,
                key=idempotency_key,
                status=201,
                body=out.model_dump(mode="json"),
            )
        return out, False

    async def list_comments(
        self,
        viewer_id: uuid.UUID,
        post_id: uuid.UUID,
        *,
        parent_id: uuid.UUID | None,
        cursor: str | None,
        limit: int,
    ) -> Page[CommentOut]:
        """Top-level comments (or replies to ``parent_id``), oldest first, tombstones included."""
        scope = f"comments.{post_id}.{parent_id}"
        async with self._sessionmaker() as session:
            post = await visible_post(session, post_id, viewer_id)
            hidden = await trust_safety.blocked_ids(session, viewer_id)
            query = select(Comment).where(
                Comment.post_id == post_id,
                Comment.parent_comment_id.is_(None)
                if parent_id is None
                else Comment.parent_comment_id == parent_id,
                Comment.moderation_state != "removed",
            )
            if hidden:
                query = query.where(Comment.author_id.notin_(hidden))
            if cursor:
                at, comment_id = _position(self._cursors.decode(cursor, scope=scope))
                query = query.where(
                    or_(
                        Comment.created_at > at,
                        and_(Comment.created_at == at, Comment.id > comment_id),
                    )
                )
            rows = list(
                (
                    await session.scalars(
                        query.order_by(Comment.created_at, Comment.id).limit(limit + 1)
                    )
                ).all()
            )
            has_more = len(rows) > limit
            rows = rows[:limit]
            data = await _comments(session, rows, viewer_id, post.author_id)
        next_cursor = (
            self._cursors.encode(
                {"at": rows[-1].created_at.isoformat(), "id": str(rows[-1].id)}, scope=scope
            )
            if has_more and rows
            else None
        )
        return Page[CommentOut](
            data=data, page=PageInfo(next_cursor=next_cursor, has_more=has_more)
        )

    async def list_replies(
        self, viewer_id: uuid.UUID, comment_id: uuid.UUID, *, cursor: str | None, limit: int
    ) -> Page[CommentOut]:
        async with self._sessionmaker() as session:
            comment = await session.get(Comment, comment_id)
            if comment is None:
                raise _comment_not_found()
            post_id = comment.post_id
        return await self.list_comments(
            viewer_id, post_id, parent_id=comment_id, cursor=cursor, limit=limit
        )

    async def update_comment(
        self, viewer_id: uuid.UUID, comment_id: uuid.UUID, body: str
    ) -> CommentOut:
        cleaned = clean_body(body)
        if not cleaned:
            raise AppError(ErrorCode.VALIDATION_FAILED, "Write something.")
        async with self._sessionmaker() as session, session.begin():
            comment = await session.get(Comment, comment_id, with_for_update=True)
            if comment is None or comment.author_id != viewer_id or comment.deleted_at is not None:
                raise _comment_not_found()
            post = await visible_post(session, comment.post_id, viewer_id)
            comment.body = cleaned
            comment.edited_at = func.now()
            await session.flush()
            await session.refresh(comment)
            [out] = await _comments(session, [comment], viewer_id, post.author_id)
            return out

    async def delete_comment(self, viewer_id: uuid.UUID, comment_id: uuid.UUID) -> None:
        """By the commenter or the post's author. Leaves a tombstone so replies keep context."""
        async with self._sessionmaker() as session, session.begin():
            comment = await session.get(Comment, comment_id, with_for_update=True)
            if comment is None or comment.deleted_at is not None:
                raise _comment_not_found()
            post = await session.get(PostRow, comment.post_id)
            if post is None or viewer_id not in (comment.author_id, post.author_id):
                raise _comment_not_found()
            comment.deleted_at = func.now()
            comment.body = ""  # the text is personal data; the tombstone keeps only structure
            await session.execute(
                update(PostRow)
                .where(PostRow.id == post.id)
                .values(comment_count=func.greatest(PostRow.comment_count - 1, 0))
            )
            if comment.parent_comment_id is not None:
                await session.execute(
                    update(Comment)
                    .where(Comment.id == comment.parent_comment_id)
                    .values(reply_count=func.greatest(Comment.reply_count - 1, 0))
                )


def _position(payload: dict[str, Any]) -> tuple[datetime, uuid.UUID]:
    return datetime.fromisoformat(str(payload["at"])), uuid.UUID(str(payload["id"]))


def _user(author: profiles.AuthorInfo) -> UserSummary:
    return UserSummary(id=author.id, handle=author.handle, display_name=author.display_name)


async def _comments(
    session: AsyncSession,
    rows: Sequence[Comment],
    viewer_id: uuid.UUID,
    post_author_id: uuid.UUID,
) -> list[CommentOut]:
    authors = await profiles.authors(session, [c.author_id for c in rows])
    result: list[CommentOut] = []
    for c in rows:
        deleted = c.deleted_at is not None
        author = authors.get(c.author_id)
        result.append(
            CommentOut(
                id=c.id,
                post_id=c.post_id,
                parent_comment_id=c.parent_comment_id,
                author=None if deleted or author is None else _user(author),
                body=None if deleted else c.body,
                language=c.language,
                reply_count=c.reply_count,
                deleted=deleted,
                created_at=c.created_at,
                edited_at=c.edited_at,
                viewer=CommentViewer(
                    can_edit=not deleted and c.author_id == viewer_id,
                    can_delete=not deleted and viewer_id in (c.author_id, post_author_id),
                ),
            )
        )
    return result
