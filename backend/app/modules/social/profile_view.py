"""Another user's profile as the viewer may see it (``PublicProfile``, PROF-008).

``404`` when either side blocked the other or the account is not active. Private accounts the
viewer does not follow, and profiles limited to connections, are *restricted*: identity stays, but
bio, home country, styles, interests, languages and counts are withheld. ``indexable`` is true only
for unrestricted public profiles whose owner opted into search-engine indexing.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode
from app.core.pagination import CursorCodec, PageInfo
from app.core.time import Clock, SystemClock
from app.modules.identity import service as identity
from app.modules.profiles import service as profiles
from app.modules.social.models import Follow, FollowStatus
from app.modules.social.models import Post as PostRow
from app.modules.social.schemas import (
    ProfileCounts,
    PublicProfile,
    RelationshipOut,
    UserSummaryPage,
)
from app.modules.trust_safety import service as trust_safety

FollowStatusName = Literal["none", "following", "requested"]


def _not_found() -> AppError:
    return AppError(ErrorCode.NOT_FOUND, "Profile not found.")


# From the composition root (connections, same layer): (relationship, can_request_connection).
RelationshipProvider = Callable[
    [AsyncSession, uuid.UUID, uuid.UUID, datetime], Awaitable[tuple[str, bool]]
]
# (state, can_request, pending_request_id, cooldown_until), also from connections.
DetailProvider = Callable[[AsyncSession, uuid.UUID, uuid.UUID, datetime], Awaitable[Any]]


class PublicProfileService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        clock: Clock | None = None,
        relationship: RelationshipProvider | None = None,
        relationship_detail: DetailProvider | None = None,
        cursors: CursorCodec | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._clock = clock or SystemClock()
        self._relationship = relationship
        self._detail = relationship_detail
        self._cursors = cursors

    async def by_handle(self, viewer_id: uuid.UUID, handle: str) -> PublicProfile:
        async with self._sessionmaker() as session:
            user_id = await profiles.user_id_for_handle(session, handle)
            if user_id is None:
                raise _not_found()
            return await self._view(session, viewer_id, user_id)

    async def by_id(self, viewer_id: uuid.UUID, user_id: uuid.UUID) -> PublicProfile:
        async with self._sessionmaker() as session:
            return await self._view(session, viewer_id, user_id)

    async def relationship(self, viewer_id: uuid.UUID, user_id: uuid.UUID) -> RelationshipOut:
        """My relationship with another user (CONN-001). Someone who blocked me does not exist
        for me (``404``); someone I blocked shows as ``blocked``."""
        async with self._sessionmaker() as session:
            if viewer_id != user_id and not await identity.is_active(session, user_id):
                raise _not_found()
            blocked_by_me, blocked_me = await trust_safety.blocks_of(session, viewer_id)
            if user_id in blocked_me:
                raise _not_found()
            followers = set(
                await session.scalars(
                    select(Follow.follower_id).where(
                        Follow.status == FollowStatus.ACTIVE,
                        or_(
                            (Follow.follower_id == viewer_id) & (Follow.followee_id == user_id),
                            (Follow.follower_id == user_id) & (Follow.followee_id == viewer_id),
                        ),
                    )
                )
            )
            if user_id in blocked_by_me:
                return RelationshipOut(
                    user_id=user_id,
                    state="blocked",
                    pending_request_id=None,
                    cooldown_until=None,
                    can_request_connection=False,
                    can_message=False,
                    is_following=False,
                    is_followed_by=False,
                )
            state, can_request, pending, cooldown = "none", False, None, None
            if viewer_id != user_id and self._detail is not None:
                detail = await self._detail(session, viewer_id, user_id, self._clock.now())
                state, can_request = detail.state, detail.can_request
                pending, cooldown = detail.pending_request_id, detail.cooldown_until
        return RelationshipOut(
            user_id=user_id,
            state=state,  # type: ignore[arg-type]
            pending_request_id=pending,
            cooldown_until=cooldown,
            can_request_connection=can_request,
            can_message=state == "connected",
            is_following=viewer_id in followers and viewer_id != user_id,
            is_followed_by=user_id in followers and viewer_id != user_id,
        )

    async def search(
        self, viewer_id: uuid.UUID, query: str, *, cursor: str | None, limit: int
    ) -> UserSummaryPage:
        """People by handle or display name, for mentions and invitations (PROF-003): blocked
        users either way and inactive accounts never appear."""
        assert self._cursors is not None
        after = None
        if cursor is not None:
            decoded = self._cursors.decode(cursor, scope="user-search")
            if decoded.get("q") != query:
                raise AppError(ErrorCode.INVALID_CURSOR, "The cursor belongs to another query.")
            after = str(decoded["h"])
        async with self._sessionmaker() as session:
            blocked_by_me, blocked_me = await trust_safety.blocks_of(session, viewer_id)
            found = await profiles.search_authors(
                session,
                query,
                exclude=frozenset(blocked_by_me | blocked_me),
                after_handle=after,
                limit=limit + 1,
            )
            more = len(found) > limit
            found = found[:limit]
            active = await identity.active_ids(session, [a.id for a in found])
        next_cursor = (
            self._cursors.encode({"q": query, "h": found[-1].handle}, scope="user-search")
            if more and found
            else None
        )
        return UserSummaryPage(
            data=[profiles.user_summary(a) for a in found if a.id in active],
            page=PageInfo(next_cursor=next_cursor),
        )

    async def _view(
        self, session: AsyncSession, viewer_id: uuid.UUID, user_id: uuid.UUID
    ) -> PublicProfile:
        own = viewer_id == user_id
        if not own and (
            not await identity.is_active(session, user_id)
            or await trust_safety.is_blocked(session, viewer_id, user_id)
        ):
            raise _not_found()
        card = await profiles.profile_card(session, user_id)
        if card is None:
            raise _not_found()
        follow = await session.scalar(
            select(Follow.status).where(
                Follow.follower_id == viewer_id, Follow.followee_id == user_id
            )
        )
        follow_status: FollowStatusName = (
            "following"
            if follow == FollowStatus.ACTIVE
            else "requested"
            if follow == FollowStatus.PENDING
            else "none"
        )
        restricted = not own and (
            (card.account_private and follow_status != "following") or card.profile_connections_only
        )
        counts = None if restricted else await self._counts(session, user_id)
        relationship, can_request = "none", False
        if not own and self._relationship is not None:
            relationship, can_request = await self._relationship(
                session, viewer_id, user_id, self._clock.now()
            )
        return PublicProfile(
            id=user_id,
            handle=card.handle,
            display_name=card.display_name,
            avatar=card.avatar,
            bio=None if restricted else card.bio,
            home_country_code=None if restricted else card.home_country_code,
            travel_styles=[] if restricted else card.travel_styles,
            interests=[] if restricted else card.interests,
            languages_spoken=[] if restricted else card.languages_spoken,
            account_visibility="private" if card.account_private else "public",
            is_restricted=restricted,
            indexable=(
                not restricted
                and not card.account_private
                and not card.profile_connections_only
                and card.search_engine_indexing
            ),
            counts=counts,
            follow_status=follow_status,
            relationship=relationship,  # type: ignore[arg-type]
            can_message=relationship == "connected",
            can_request_connection=can_request,
        )

    @staticmethod
    async def _counts(session: AsyncSession, user_id: uuid.UUID) -> ProfileCounts:
        posts = await session.scalar(
            select(func.count())
            .select_from(PostRow)
            .where(
                PostRow.author_id == user_id,
                PostRow.status == "published",
                PostRow.moderation_state != "removed",
            )
        )
        followers = await session.scalar(
            select(func.count())
            .select_from(Follow)
            .where(Follow.followee_id == user_id, Follow.status == FollowStatus.ACTIVE)
        )
        following = await session.scalar(
            select(func.count())
            .select_from(Follow)
            .where(Follow.follower_id == user_id, Follow.status == FollowStatus.ACTIVE)
        )
        return ProfileCounts(posts=posts or 0, followers=followers or 0, following=following or 0)
