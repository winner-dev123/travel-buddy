"""Public interface of the trust_safety module: blocks (BL-1.12, SAFE-001).

A block is immediate and bidirectional. Modules above this layer (social, feed, messaging,
discovery) read :func:`blocked_ids` / :func:`is_blocked` to hide each user from the other, and
can register ``on_block`` hooks (wired by the composition root) that run in the SAME transaction,
e.g. removing follows in both directions. The blocked user is never notified.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.pagination import CursorCodec, Page, PageInfo
from app.modules.platform import service as platform
from app.modules.profiles import service as profiles
from app.modules.profiles.schemas import UserSummary
from app.modules.trust_safety.models import UserBlock

BlockHook = Callable[[AsyncSession, uuid.UUID, uuid.UUID], Awaitable[None]]


async def is_blocked(session: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> bool:
    """True when either user blocked the other."""
    if a == b:
        return False
    found = await session.scalar(
        select(UserBlock.blocker_id).where(
            or_(
                and_(UserBlock.blocker_id == a, UserBlock.blocked_id == b),
                and_(UserBlock.blocker_id == b, UserBlock.blocked_id == a),
            )
        )
    )
    return found is not None


async def blocked_ids(session: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Everyone this user blocked or was blocked by: hide them from each other."""
    rows = await session.execute(
        select(UserBlock.blocker_id, UserBlock.blocked_id).where(
            or_(UserBlock.blocker_id == user_id, UserBlock.blocked_id == user_id)
        )
    )
    return {blocked if blocker == user_id else blocker for blocker, blocked in rows.all()}


class BlockService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        cursors: CursorCodec,
        on_block: Sequence[BlockHook] = (),
    ) -> None:
        self._sessionmaker = sessionmaker
        self._cursors = cursors
        self._on_block = tuple(on_block)

    async def block(self, blocker_id: uuid.UUID, blocked_id: uuid.UUID) -> None:
        if blocker_id == blocked_id:
            raise AppError(
                ErrorCode.VALIDATION_FAILED,
                "You can't block yourself.",
                errors=[FieldError(field="/userId", code="self", message="Cannot block yourself.")],
            )
        async with self._sessionmaker() as session, session.begin():
            if blocked_id not in await profiles.authors(session, [blocked_id]):
                raise AppError(ErrorCode.NOT_FOUND, "User not found.")
            inserted = await session.execute(
                insert(UserBlock)
                .values(blocker_id=blocker_id, blocked_id=blocked_id)
                .on_conflict_do_nothing()
                .returning(UserBlock.blocker_id)
            )
            if inserted.first() is None:
                return  # already blocked: idempotent
            for hook in self._on_block:
                await hook(session, blocker_id, blocked_id)
            platform.record_event(
                session,
                aggregate_type="user",
                aggregate_id=blocker_id,
                event_type="user.blocked",
                payload={"blocker_id": str(blocker_id), "blocked_id": str(blocked_id)},
            )

    async def unblock(self, blocker_id: uuid.UUID, blocked_id: uuid.UUID) -> None:
        """Does not restore follows or connections."""
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                delete(UserBlock).where(
                    UserBlock.blocker_id == blocker_id, UserBlock.blocked_id == blocked_id
                )
            )

    async def list_blocked(
        self, blocker_id: uuid.UUID, *, cursor: str | None, limit: int
    ) -> Page[UserSummary]:
        scope = f"blocks.{blocker_id}"
        async with self._sessionmaker() as session:
            query = select(UserBlock).where(UserBlock.blocker_id == blocker_id)
            if cursor:
                position = self._cursors.decode(cursor, scope=scope)
                at = datetime.fromisoformat(str(position["at"]))
                other = uuid.UUID(str(position["id"]))
                query = query.where(
                    or_(
                        UserBlock.created_at < at,
                        and_(UserBlock.created_at == at, UserBlock.blocked_id < other),
                    )
                )
            rows = list(
                (
                    await session.scalars(
                        query.order_by(
                            UserBlock.created_at.desc(), UserBlock.blocked_id.desc()
                        ).limit(limit + 1)
                    )
                ).all()
            )
            has_more = len(rows) > limit
            rows = rows[:limit]
            users = await profiles.authors(session, [r.blocked_id for r in rows])
        data = [profiles.user_summary(users[r.blocked_id]) for r in rows if r.blocked_id in users]
        next_cursor = (
            self._cursors.encode(
                {"at": rows[-1].created_at.isoformat(), "id": str(rows[-1].blocked_id)},
                scope=scope,
            )
            if has_more and rows
            else None
        )
        return Page[UserSummary](
            data=data, page=PageInfo(next_cursor=next_cursor, has_more=has_more)
        )
