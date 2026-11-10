"""Destination guides and audio tours (BL-4.07; GUIDE-004, GUIDE-005, GUIDE-006).

* Only ``published`` content whose rights have not expired is served, for active destinations.
* ``free`` content is readable by anyone, guides even anonymously (server-rendered SEO pages).
  ``premium`` needs ``guides.premium`` / ``audio_tours.premium``; ``purchasable`` needs that or the
  content purchase (entitlement ``content:guide:<id>`` / ``content:audio_tour:<id>``). Anonymous
  callers get ``401``, signed-in callers without the entitlement ``403 entitlement_required``.
* Lists show one entry per guide (``slug``): its latest version in the locale that best matches
  the reader's ``Accept-Language`` (then English, then any).
* Audio tour stops carry a geofence radius that the device evaluates; no location is sent here.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import AppError, ErrorCode
from app.core.time import Clock
from app.modules.billing import service as billing
from app.modules.destinations import service as destinations
from app.modules.guides.models import AudioTour as AudioTourRow
from app.modules.guides.models import AudioTourStop as StopRow
from app.modules.guides.models import DestinationGuide
from app.modules.guides.schemas import (
    AudioTour,
    AudioTourStop,
    AudioTourSummary,
    AudioTourSummaryList,
    Guide,
    GuideSection,
    GuideSummary,
    GuideSummaryList,
)
from app.modules.media import service as media

ContentKind = Literal["guide", "audio_tour"]
_PREMIUM = {
    "guide": billing.Feature.GUIDES_PREMIUM,
    "audio_tour": billing.Feature.AUDIO_TOURS_PREMIUM,
}


def _not_found(what: str) -> AppError:
    return AppError(ErrorCode.NOT_FOUND, f"{what} not found.")


def _live(
    model: type[DestinationGuide] | type[AudioTourRow], now: datetime
) -> list[ColumnElement[bool]]:
    return [
        model.status == "published",
        model.published_at.is_not(None),
        or_(model.rights_expire_at.is_(None), model.rights_expire_at > now),
    ]


def _locale_rank(locale: str, preferences: Sequence[str]) -> int:
    lowered = [p.lower() for p in preferences]
    if locale.lower() in lowered:
        return lowered.index(locale.lower())
    language = locale.split("-", 1)[0].lower()
    primaries = [p.split("-", 1)[0] for p in lowered]
    if language in primaries:
        return len(lowered) + primaries.index(language)
    return 2 * len(lowered) + (0 if language == "en" else 1)


def _best[Row: (DestinationGuide, AudioTourRow)](
    rows: Sequence[Row], preferences: Sequence[str]
) -> list[Row]:
    """One row per slug: the best locale for the reader, then the newest version."""
    by_slug: dict[str, list[Row]] = defaultdict(list)
    for row in rows:
        by_slug[row.slug].append(row)
    return [
        min(group, key=lambda r: (_locale_rank(r.locale, preferences), -r.version))
        for group in by_slug.values()
    ]


async def _entitled(
    session: AsyncSession,
    viewer_id: uuid.UUID | None,
    *,
    kind: ContentKind,
    content_id: uuid.UUID,
    tier: str,
    at: datetime,
) -> bool:
    if tier == "free":
        return True
    if viewer_id is None:
        return False
    snapshot = await billing.snapshot(session, viewer_id, at=at)
    if snapshot.has(_PREMIUM[kind]):
        return True
    return tier == "purchasable" and snapshot.has_content(f"content:{kind}:{content_id}")


def _locked(viewer_id: uuid.UUID | None, kind: ContentKind) -> AppError:
    if viewer_id is None:
        return AppError(ErrorCode.UNAUTHENTICATED, "Sign in to read this.")
    return AppError(
        ErrorCode.ENTITLEMENT_REQUIRED,
        "This is premium content.",
        extensions={"entitlement": _PREMIUM[kind].value},
    )


class GuideService:
    def __init__(self, *, sessionmaker: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self._sessionmaker = sessionmaker
        self._clock = clock

    async def _destination(
        self, session: AsyncSession, destination_id: uuid.UUID, preferences: Sequence[str]
    ) -> None:
        if not await destinations.is_active(session, destination_id):
            raise _not_found("Destination")

    # ─────────────────────────────── guides ───────────────────────────────

    async def list_guides(
        self,
        destination_id: uuid.UUID,
        viewer_id: uuid.UUID | None,
        *,
        preferences: Sequence[str],
    ) -> GuideSummaryList:
        now = self._clock.now()
        async with self._sessionmaker() as session:
            await self._destination(session, destination_id, preferences)
            rows = (
                await session.scalars(
                    select(DestinationGuide).where(
                        DestinationGuide.destination_id == destination_id,
                        *_live(DestinationGuide, now),
                    )
                )
            ).all()
            data = []
            for row in sorted(
                _best(rows, preferences),
                key=lambda r: (r.tier != "free", r.title.casefold()),
            ):
                data.append(
                    GuideSummary(
                        id=row.id,
                        destination_id=row.destination_id,
                        locale=row.locale,
                        title=row.title,
                        summary=row.summary,
                        tier=row.tier,  # type: ignore[arg-type]
                        entitled=await _entitled(
                            session,
                            viewer_id,
                            kind="guide",
                            content_id=row.id,
                            tier=row.tier,
                            at=now,
                        ),
                        product_id=row.product_id,
                        version=row.version,
                        published_at=row.published_at,  # type: ignore[arg-type]
                    )
                )
        return GuideSummaryList(data=data)

    async def get_guide(
        self, guide_id: uuid.UUID, viewer_id: uuid.UUID | None, *, preferences: Sequence[str]
    ) -> Guide:
        now = self._clock.now()
        async with self._sessionmaker() as session:
            row = await session.scalar(
                select(DestinationGuide).where(
                    DestinationGuide.id == guide_id, *_live(DestinationGuide, now)
                )
            )
            if row is None:
                raise _not_found("Guide")
            summaries = await destinations.summaries_by_id(
                session, [row.destination_id], preferences
            )
            if row.destination_id not in summaries:
                raise _not_found("Guide")
            if not await _entitled(
                session, viewer_id, kind="guide", content_id=row.id, tier=row.tier, at=now
            ):
                raise _locked(viewer_id, "guide")
        return Guide(
            id=row.id,
            destination=summaries[row.destination_id],
            locale=row.locale,
            title=row.title,
            summary=row.summary,
            sections=[GuideSection.model_validate(section) for section in row.content],
            tier=row.tier,  # type: ignore[arg-type]
            version=row.version,
            content_license=row.content_license,
            attribution=row.attribution,
            published_at=row.published_at,  # type: ignore[arg-type]
            updated_at=row.updated_at,
        )

    # ─────────────────────────────── audio tours ───────────────────────────────

    async def list_tours(
        self,
        destination_id: uuid.UUID,
        viewer_id: uuid.UUID | None,
        *,
        preferences: Sequence[str],
    ) -> AudioTourSummaryList:
        now = self._clock.now()
        async with self._sessionmaker() as session:
            await self._destination(session, destination_id, preferences)
            rows = _best(
                (
                    await session.scalars(
                        select(AudioTourRow).where(
                            AudioTourRow.destination_id == destination_id,
                            *_live(AudioTourRow, now),
                        )
                    )
                ).all(),
                preferences,
            )
            counts: dict[uuid.UUID, int] = defaultdict(int)
            durations: dict[uuid.UUID, int] = defaultdict(int)
            if rows:
                for stop in await session.scalars(
                    select(StopRow).where(StopRow.tour_id.in_([r.id for r in rows]))
                ):
                    counts[stop.tour_id] += 1
                    durations[stop.tour_id] += stop.duration_s
            data = []
            for row in sorted(rows, key=lambda r: (r.tier != "free", r.title.casefold())):
                data.append(
                    AudioTourSummary(
                        id=row.id,
                        destination_id=row.destination_id,
                        locale=row.locale,
                        title=row.title,
                        description=row.description,
                        tier=row.tier,  # type: ignore[arg-type]
                        entitled=await _entitled(
                            session,
                            viewer_id,
                            kind="audio_tour",
                            content_id=row.id,
                            tier=row.tier,
                            at=now,
                        ),
                        total_duration_s=durations[row.id],
                        stop_count=counts[row.id],
                        version=row.version,
                    )
                )
        return AudioTourSummaryList(data=data)

    async def get_tour(
        self, tour_id: uuid.UUID, viewer_id: uuid.UUID, *, preferences: Sequence[str]
    ) -> AudioTour:
        now = self._clock.now()
        async with self._sessionmaker() as session:
            row = await session.scalar(
                select(AudioTourRow).where(AudioTourRow.id == tour_id, *_live(AudioTourRow, now))
            )
            if row is None:
                raise _not_found("Audio tour")
            summaries = await destinations.summaries_by_id(
                session, [row.destination_id], preferences
            )
            if row.destination_id not in summaries:
                raise _not_found("Audio tour")
            if not await _entitled(
                session, viewer_id, kind="audio_tour", content_id=row.id, tier=row.tier, at=now
            ):
                raise _locked(viewer_id, "audio_tour")
            stops = list(
                await session.scalars(
                    select(StopRow).where(StopRow.tour_id == row.id).order_by(StopRow.sort_order)
                )
            )
            places = await destinations.place_summaries(
                session, [s.place_id for s in stops], preferences
            )
            audio = await media.refs(session, [s.audio_media_id for s in stops])
        shown = [s for s in stops if s.place_id in places and s.audio_media_id in audio]
        return AudioTour(
            id=row.id,
            destination=summaries[row.destination_id],
            locale=row.locale,
            title=row.title,
            description=row.description,
            tier=row.tier,  # type: ignore[arg-type]
            version=row.version,
            total_duration_s=sum(s.duration_s for s in shown),
            stops=[
                AudioTourStop(
                    id=s.id,
                    sort_order=s.sort_order,
                    place=places[s.place_id],
                    title=s.title,
                    audio=audio[s.audio_media_id],
                    transcript=s.transcript,
                    trigger_radius_m=s.trigger_radius_m,
                    duration_s=s.duration_s,
                )
                for s in shown
            ],
            content_license=row.content_license,
        )
