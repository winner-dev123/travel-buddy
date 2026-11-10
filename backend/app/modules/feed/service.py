"""Public interface of the feed module (BL-1.13; FEED-001..007, FEED-020).

Read path (docs/02 section 7.4): resolve the feed's source through the FEED-001 chain, gather
candidates from the social module (visibility, moderation, blocks and hidden posts filtered in
SQL), score them with the pure v1 ranker, diversify, and store the ranked IDs as a 15-minute
snapshot. The cursor is ``(snapshot, offset)``, so pages stay stable while new posts arrive; an
expired snapshot is recomputed and the page says ``reset``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.pagination import CursorCodec
from app.core.time import Clock
from app.modules.destinations import service as destinations
from app.modules.feed.domain import (
    WEIGHTS_V1,
    ViewerSignals,
    Weights,
    diversify,
    engagement_quality,
    haversine_km,
    recency,
    score,
)
from app.modules.feed.models import FeedbackKind, FeedFeedback, FeedSession
from app.modules.feed.schemas import FeedContext, FeedFeedbackRequest, FeedResult
from app.modules.location import service as location
from app.modules.platform import service as platform
from app.modules.profiles import service as profiles
from app.modules.social import service as social
from app.modules.trust_safety import service as trust_safety

SNAPSHOT_TTL = timedelta(minutes=15)
SNAPSHOT_MAX = 500
WINDOW = timedelta(days=30)
WIDE_WINDOW = timedelta(days=365)
_CURSOR_SCOPE = "feed"


@dataclass(frozen=True, slots=True)
class FeedParams:
    tab: str = "for_you"
    destination_id: uuid.UUID | None = None
    near: str | None = None
    near_ts: datetime | None = None  # when the device took the fix (LOC-007)
    near_city_level: bool = False  # coarse reading: city only (LOC-008)
    radius_km: int = 10
    country: str | None = None
    kinds: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    languages: tuple[str, ...] | None = None  # None = the user's content_languages preference
    sort: str = "ranked"
    saved_destinations_only: bool = False
    cursor: str | None = None
    limit: int = 20


@dataclass(slots=True)
class _Step:
    source: str
    destination_ids: list[uuid.UUID] = field(default_factory=list)
    author_ids: list[uuid.UUID] | None = None
    interest_tags: list[str] = field(default_factory=list)
    global_scope: bool = False
    explicit: bool = False


def _invalid(field_name: str, code: str, message: str) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_FAILED,
        message,
        errors=[FieldError(field=field_name, code=code, message=message)],
    )


class FeedService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        cursors: CursorCodec,
        clock: Clock,
        weights: Weights = WEIGHTS_V1,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._cursors = cursors
        self._clock = clock
        self._weights = weights

    async def feed(
        self, viewer_id: uuid.UUID, params: FeedParams, *, preferences: Sequence[str]
    ) -> FeedResult:
        reset = False
        if params.cursor:
            position = self._cursors.decode(params.cursor, scope=_CURSOR_SCOPE)
            async with self._sessionmaker() as session:
                snapshot = await session.get(FeedSession, uuid.UUID(str(position["s"])))
                now = await session.scalar(select(func.now()))
                if (
                    snapshot is not None
                    and snapshot.user_id == viewer_id
                    and now is not None
                    and snapshot.expires_at > now
                ):
                    return await self._page(
                        session, snapshot, int(position["o"]), params.limit, viewer_id, preferences
                    )
            reset = True  # the snapshot expired: recompute and tell the client to replace
        async with self._sessionmaker() as session, session.begin():
            snapshot = await self._compute(session, viewer_id, params)
            result = await self._page(session, snapshot, 0, params.limit, viewer_id, preferences)
        return result.model_copy(update={"reset": reset})

    async def feedback(self, viewer_id: uuid.UUID, request: FeedFeedbackRequest) -> None:
        """Idempotent. Hidden posts never come back; ``see_less_author`` penalizes the author."""
        async with self._sessionmaker() as session, session.begin():
            visible = await social.assemble_visible(session, [request.post_id], viewer_id, [])
            if not visible:
                raise AppError(ErrorCode.NOT_FOUND, "Post not found.")
            await session.execute(
                insert(FeedFeedback)
                .values(
                    user_id=viewer_id,
                    post_id=request.post_id,
                    kind=request.kind,
                    author_id=visible[0].author.id,
                )
                .on_conflict_do_nothing()
            )

    # ─────────────────────────────── computation ───────────────────────────────

    async def _compute(
        self, session: AsyncSession, viewer_id: uuid.UUID, params: FeedParams
    ) -> FeedSession:
        now = self._clock.now()
        prefs = await profiles.viewer_preferences(session, viewer_id)
        filter_languages = list(
            params.languages if params.languages is not None else prefs.content_languages
        )
        match_languages = frozenset(
            lang.split("-", 1)[0].lower() for lang in (prefs.content_languages or [prefs.ui_locale])
        )
        blocked = await trust_safety.blocked_ids(session, viewer_id)
        feedback = (
            await session.execute(
                select(FeedFeedback.kind, FeedFeedback.post_id, FeedFeedback.author_id).where(
                    FeedFeedback.user_id == viewer_id
                )
            )
        ).all()
        hidden = [p for k, p, _ in feedback if k != FeedbackKind.SEE_LESS_AUTHOR]
        see_less = frozenset(a for k, _, a in feedback if k == FeedbackKind.SEE_LESS_AUTHOR)

        point, radius = None, None
        if params.tab == "nearby" or (params.near and params.tab == "for_you"):
            if params.near:
                try:
                    point = destinations.coarse_point(params.near)
                except ValueError as exc:
                    raise _invalid("/near", "invalid", "near must be 'lat,lng'.") from exc
                destinations.ensure_fresh_fix(params.near_ts, self._clock.now(), field="/near_ts")
            elif params.tab == "nearby":
                raise _invalid("/near", "required", "The Nearby tab needs your location.")
        steps = await self._steps(session, viewer_id, params, prefs.interests, point)
        if params.tab == "nearby":
            radius = float(params.radius_km)

        chosen: _Step | None = None
        found: list[social.Candidate] = []
        for step in steps:
            found = await self._candidates(
                session, viewer_id, step, params, filter_languages, hidden, blocked, now
            )
            chosen = step
            if found or step.explicit:
                break
        assert chosen is not None

        distances: dict[uuid.UUID, float] = {}
        if point is not None and radius is not None:
            centroids = await destinations.centroids(
                session, [c.primary_destination_id for c in found if c.primary_destination_id]
            )
            distances = {
                c.post_id: haversine_km(point, centroids[c.primary_destination_id])
                for c in found
                if c.primary_destination_id in centroids
            }
        signals = ViewerSignals(
            interests=frozenset(prefs.interests),
            languages=match_languages,
            see_less_authors=see_less,
        )
        if params.sort == "recent":
            ordered = sorted(found, key=lambda c: c.published_at, reverse=True)
        elif params.sort == "popular":
            ordered = sorted(
                found,
                key=lambda c: (
                    engagement_quality(c),
                    recency((now - c.published_at).total_seconds() / 3600, 72.0),
                ),
                reverse=True,
            )
        else:
            ordered = sorted(
                found,
                key=lambda c: score(
                    c,
                    now=now,
                    viewer=signals,
                    weights=self._weights,
                    distance_km=distances.get(c.post_id),
                    radius_km=radius,
                ),
                reverse=True,
            )
        ranked = diversify(ordered)[:SNAPSHOT_MAX]

        await session.execute(
            delete(FeedSession).where(
                FeedSession.user_id == viewer_id, FeedSession.expires_at < func.now()
            )
        )
        snapshot = FeedSession(
            user_id=viewer_id,
            post_ids=[c.post_id for c in ranked],
            context={
                "destination_id": str(chosen.destination_ids[0])
                if chosen.destination_ids
                else None,
                "source": chosen.source,
                "radius_km": radius,
            },
            weights_version=self._weights.version,
            expires_at=now + SNAPSHOT_TTL,
        )
        session.add(snapshot)
        await session.flush()
        return snapshot

    async def _steps(
        self,
        session: AsyncSession,
        viewer_id: uuid.UUID,
        params: FeedParams,
        interests: list[str],
        point: tuple[float, float] | None,
    ) -> list[_Step]:
        """The FEED-001 chain for this request; the first step with content wins."""
        if params.tab == "following":
            authors = await social.followed_author_ids(session, viewer_id)
            return [_Step("following", author_ids=authors, explicit=True)]
        if params.tab == "nearby":
            assert point is not None
            resolved = await destinations.resolve_point(session, *point)
            if resolved is None:
                raise AppError(
                    ErrorCode.LOCATION_UNRESOLVABLE,
                    "Your location is outside the destinations we cover yet.",
                )
            city = await destinations.city_of(session, resolved)
            return [_Step("gps", destination_ids=[city], explicit=True)]

        if params.destination_id is not None:
            if not await destinations.is_active(session, params.destination_id):
                raise AppError(ErrorCode.NOT_FOUND, "Destination not found.")
            return [_Step("selected", destination_ids=[params.destination_id], explicit=True)]
        if params.country is not None:
            country = await destinations.country_destination_id(session, params.country)
            if country is None:
                raise AppError(ErrorCode.NOT_FOUND, "Destination not found.")
            return [_Step("selected", destination_ids=[country], explicit=True)]

        steps: list[_Step] = []
        if point is not None:
            resolved = await destinations.resolve_point(session, *point)
            if resolved is not None and params.near_city_level:
                resolved = await destinations.city_of(session, resolved)
            if resolved is not None:
                steps.append(_Step("gps", destination_ids=[resolved]))
        browse, upcoming = await location.selected_destinations(session, viewer_id)
        if params.tab == "destinations" or params.saved_destinations_only:
            chosen = list(dict.fromkeys([d for d in [browse, *upcoming] if d is not None]))
            if chosen:
                steps.append(
                    _Step("selected" if browse else "upcoming_trip", destination_ids=chosen)
                )
            if params.saved_destinations_only:
                return steps or [_Step("selected", explicit=True)]
        else:
            if browse is not None:
                steps.append(_Step("selected", destination_ids=[browse]))
            if upcoming:
                steps.append(_Step("upcoming_trip", destination_ids=upcoming))
        if interests:
            steps.append(_Step("interests", interest_tags=interests[:10], global_scope=True))
        steps.append(_Step("global", global_scope=True))
        return steps

    async def _candidates(
        self,
        session: AsyncSession,
        viewer_id: uuid.UUID,
        step: _Step,
        params: FeedParams,
        languages: list[str],
        hidden: list[uuid.UUID],
        blocked: set[uuid.UUID],
        now: datetime,
    ) -> list[social.Candidate]:
        parents: list[uuid.UUID] = []
        if len(step.destination_ids) == 1:
            ancestry = await destinations.ancestry(session, step.destination_ids[0]) or []
            parents = ancestry[:-1]
        tags = list(params.tags) or step.interest_tags
        result: list[social.Candidate] = []
        for window in (WINDOW, WIDE_WINDOW):  # widen when the destination is quiet
            query = social.CandidateQuery(
                viewer_id=viewer_id,
                since=now - window,
                destination_ids=step.destination_ids,
                parent_destination_ids=parents,
                author_ids=step.author_ids,
                global_scope=step.global_scope,
                kinds=params.kinds,
                tags=tags,
                languages=languages,
                exclude_post_ids=hidden,
                exclude_author_ids=list(blocked),
            )
            if not (query.destination_ids or query.author_ids is not None or query.global_scope):
                return []
            result = await social.candidates(session, query)
            if len(result) >= params.limit:
                break
        return result

    async def _page(
        self,
        session: AsyncSession,
        snapshot: FeedSession,
        offset: int,
        limit: int,
        viewer_id: uuid.UUID,
        preferences: Sequence[str],
    ) -> FeedResult:
        ids = list(snapshot.post_ids)[offset : offset + limit]
        hidden = (
            set(
                (
                    await session.scalars(
                        select(FeedFeedback.post_id).where(
                            FeedFeedback.user_id == viewer_id,
                            FeedFeedback.post_id.in_(ids),
                            FeedFeedback.kind != FeedbackKind.SEE_LESS_AUTHOR,
                        )
                    )
                ).all()
            )
            if ids
            else set()
        )
        posts = await social.assemble_visible(
            session, [i for i in ids if i not in hidden], viewer_id, preferences
        )
        has_more = offset + limit < len(snapshot.post_ids)
        next_cursor = (
            self._cursors.encode({"s": str(snapshot.id), "o": offset + limit}, scope=_CURSOR_SCOPE)
            if has_more
            else None
        )
        context: dict[str, Any] = snapshot.context
        destination = None
        if context.get("destination_id"):
            destination_id = uuid.UUID(str(context["destination_id"]))
            destination = (
                await destinations.summaries_by_id(session, [destination_id], preferences)
            ).get(destination_id)
        return FeedResult(
            data=[p.as_json() for p in posts],
            next_cursor=next_cursor,
            has_more=has_more,
            reset=False,
            context=FeedContext(
                destination=destination, source=context["source"], radius_km=context["radius_km"]
            ),
        )


async def purge_expired(session: AsyncSession) -> int:
    """Feedback after 180 days (docs/04 §14); feed snapshots an hour past their expiry."""
    return await platform.delete_batch(
        session, FeedFeedback, FeedFeedback.created_at < platform.ago(days=180)
    ) + await platform.delete_batch(
        session, FeedSession, FeedSession.expires_at < platform.ago(hours=1)
    )


async def export_user_data(
    session: AsyncSession, user_id: uuid.UUID
) -> dict[str, list[dict[str, object]]]:
    """Personal-data export (BL-6.03; AUTH-011): what this module holds about the user."""
    from app.modules.feed.models import FeedFeedback

    return {
        "feed_feedback": await platform.export_rows(
            session, FeedFeedback, FeedFeedback.user_id == user_id
        ),
    }
