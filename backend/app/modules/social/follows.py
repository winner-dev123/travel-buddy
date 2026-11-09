"""Follows and follow requests (POST-006, PROF-004).

Following a public account is immediate; following a private account creates a pending request
the owner approves or declines. Follower lists of private accounts are visible only to the owner
and their followers.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.pagination import CursorCodec, Page, PageInfo
from app.modules.platform import service as platform
from app.modules.profiles import service as profiles
from app.modules.social.models import Follow, FollowStatus
from app.modules.social.schemas import FollowState, UserSummary
from app.modules.trust_safety import service as trust_safety


def _user_not_found() -> AppError:
    return AppError(ErrorCode.NOT_FOUND, "User not found.")


class FollowService:
    def __init__(
        self, *, sessionmaker: async_sessionmaker[AsyncSession], cursors: CursorCodec
    ) -> None:
        self._sessionmaker = sessionmaker
        self._cursors = cursors

    async def follow(self, follower_id: uuid.UUID, followee_id: uuid.UUID) -> FollowState:
        if follower_id == followee_id:
            raise AppError(
                ErrorCode.VALIDATION_FAILED,
                "You can't follow yourself.",
                errors=[
                    FieldError(field="/userId", code="self", message="Cannot follow yourself.")
                ],
            )
        async with self._sessionmaker() as session, session.begin():
            target = (await profiles.authors(session, [followee_id])).get(followee_id)
            if target is None or await trust_safety.is_blocked(session, follower_id, followee_id):
                raise _user_not_found()  # a blocked user learns nothing (SAFE-001)
            status = FollowStatus.PENDING if target.account_private else FollowStatus.ACTIVE
            inserted = await session.execute(
                insert(Follow)
                .values(follower_id=follower_id, followee_id=followee_id, status=status)
                .on_conflict_do_nothing()
                .returning(Follow.status)
            )
            created = inserted.scalar_one_or_none()
            if created is None:  # already following or requested: idempotent
                current = await session.scalar(
                    select(Follow.status).where(
                        Follow.follower_id == follower_id, Follow.followee_id == followee_id
                    )
                )
                return _state(str(current))
            platform.record_event(
                session,
                aggregate_type="user",
                aggregate_id=followee_id,
                event_type="follow.requested"
                if status == FollowStatus.PENDING
                else "follow.created",
                payload={"follower_id": str(follower_id), "followee_id": str(followee_id)},
            )
            return _state(status)

    async def unfollow(self, follower_id: uuid.UUID, followee_id: uuid.UUID) -> None:
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                delete(Follow).where(
                    Follow.follower_id == follower_id, Follow.followee_id == followee_id
                )
            )

    async def decide(self, owner_id: uuid.UUID, requester_id: uuid.UUID, *, approve: bool) -> None:
        async with self._sessionmaker() as session, session.begin():
            match = (
                (Follow.follower_id == requester_id)
                & (Follow.followee_id == owner_id)
                & (Follow.status == FollowStatus.PENDING)
            )
            if approve:
                result = await session.execute(
                    update(Follow)
                    .where(match)
                    .values(status=FollowStatus.ACTIVE)
                    .returning(Follow.follower_id)
                )
            else:
                result = await session.execute(
                    delete(Follow).where(match).returning(Follow.follower_id)
                )
            if result.first() is None:
                raise AppError(ErrorCode.NOT_FOUND, "Follow request not found.")
            if approve:
                platform.record_event(
                    session,
                    aggregate_type="user",
                    aggregate_id=owner_id,
                    event_type="follow.approved",
                    payload={"follower_id": str(requester_id), "followee_id": str(owner_id)},
                )

    async def requests(
        self, owner_id: uuid.UUID, *, cursor: str | None, limit: int
    ) -> Page[UserSummary]:
        return await self._list(
            "requests",
            owner_id,
            Follow.followee_id == owner_id,
            Follow.status == FollowStatus.PENDING,
            user_column=Follow.follower_id,
            cursor=cursor,
            limit=limit,
        )

    async def followers(
        self, viewer_id: uuid.UUID, user_id: uuid.UUID, *, cursor: str | None, limit: int
    ) -> Page[UserSummary]:
        await self._check_list_access(viewer_id, user_id)
        return await self._list(
            "followers",
            user_id,
            Follow.followee_id == user_id,
            Follow.status == FollowStatus.ACTIVE,
            user_column=Follow.follower_id,
            cursor=cursor,
            limit=limit,
        )

    async def following(
        self, viewer_id: uuid.UUID, user_id: uuid.UUID, *, cursor: str | None, limit: int
    ) -> Page[UserSummary]:
        await self._check_list_access(viewer_id, user_id)
        return await self._list(
            "following",
            user_id,
            Follow.follower_id == user_id,
            Follow.status == FollowStatus.ACTIVE,
            user_column=Follow.followee_id,
            cursor=cursor,
            limit=limit,
        )

    async def _check_list_access(self, viewer_id: uuid.UUID, user_id: uuid.UUID) -> None:
        async with self._sessionmaker() as session:
            target = (await profiles.authors(session, [user_id])).get(user_id)
            if target is None or await trust_safety.is_blocked(session, viewer_id, user_id):
                raise _user_not_found()
            if target.account_private and viewer_id != user_id:
                follows = await session.scalar(
                    select(Follow.status).where(
                        Follow.follower_id == viewer_id,
                        Follow.followee_id == user_id,
                        Follow.status == FollowStatus.ACTIVE,
                    )
                )
                if follows is None:
                    raise AppError(ErrorCode.FORBIDDEN, "This account is private.")

    async def _list(
        self,
        name: str,
        subject_id: uuid.UUID,
        *conditions: Any,
        user_column: Any,
        cursor: str | None,
        limit: int,
    ) -> Page[UserSummary]:
        scope = f"follows.{name}.{subject_id}"
        async with self._sessionmaker() as session:
            query = select(Follow.created_at, user_column).where(*conditions)
            if cursor:
                position = self._cursors.decode(cursor, scope=scope)
                at = datetime.fromisoformat(str(position["at"]))
                other = uuid.UUID(str(position["id"]))
                query = query.where(
                    or_(Follow.created_at < at, and_(Follow.created_at == at, user_column < other))
                )
            rows = (
                await session.execute(
                    query.order_by(Follow.created_at.desc(), user_column.desc()).limit(limit + 1)
                )
            ).all()
            has_more = len(rows) > limit
            rows = rows[:limit]
            users = await profiles.authors(session, [r[1] for r in rows])
        data = [profiles.user_summary(u) for u in (users.get(r[1]) for r in rows) if u is not None]
        next_cursor = (
            self._cursors.encode(
                {"at": rows[-1][0].isoformat(), "id": str(rows[-1][1])}, scope=scope
            )
            if has_more and rows
            else None
        )
        return Page[UserSummary](
            data=data, page=PageInfo(next_cursor=next_cursor, has_more=has_more)
        )


def _state(status: str) -> FollowState:
    return FollowState(status="following" if status == FollowStatus.ACTIVE else "requested")
