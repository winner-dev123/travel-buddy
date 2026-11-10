"""Traveler discovery sessions (BL-2.02; DISC-001/002/003/006, LOC-009, ADR-0005).

- Discovery needs ``discovery_enabled`` and a recorded ``traveler_discovery`` consent.
- A session is scoped to a city, plus a neighbourhood only when the user chose that
  granularity. A GPS point is resolved with PostGIS and dropped: no coordinate is stored,
  logged or returned.
- Sessions last 1-72 h (default 24) and stop counting the moment they expire (query filter, no
  job needed). One open session per user; starting a new one ends the previous one.
- At most 10 session starts (destination switches) a day (DISC-009, T-LOC-03).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import AppError, ErrorCode, FieldError
from app.modules.destinations import service as destinations
from app.modules.location.models import (
    DiscoverySource,
    DiscoveryVisibility,
    TravelerDiscoverySession,
)
from app.modules.location.schemas import (
    DiscoveryByDestinationRequest,
    DiscoveryByGpsRequest,
    DiscoverySessionOut,
)
from app.modules.platform import service as platform
from app.modules.profiles import service as profiles

DAILY_SWITCH_LIMIT = 10


def _active() -> ColumnElement[bool]:
    return (TravelerDiscoverySession.ended_at.is_(None)) & (
        TravelerDiscoverySession.expires_at > func.now()
    )


async def require_discovery(
    session: AsyncSession, user_id: uuid.UUID
) -> profiles.DiscoverySettings:
    settings = await profiles.discovery_settings(session, user_id)
    if not settings.consented:
        raise AppError(
            ErrorCode.CONSENT_REQUIRED,
            "Traveler discovery needs your consent first.",
            extensions={"consent_type": "traveler_discovery"},
        )
    if not settings.enabled:
        raise AppError(
            ErrorCode.DISCOVERY_DISABLED, "Turn on traveler discovery in your privacy settings."
        )
    return settings


async def active_session(
    session: AsyncSession, user_id: uuid.UUID
) -> TravelerDiscoverySession | None:
    found: TravelerDiscoverySession | None = await session.scalar(
        select(TravelerDiscoverySession).where(
            TravelerDiscoverySession.user_id == user_id, _active()
        )
    )
    return found


async def visible_sessions_in(
    session: AsyncSession, destination_id: uuid.UUID, exclude: uuid.UUID
) -> Sequence[TravelerDiscoverySession]:
    """Active, visible sessions in a city (the discover query's candidate set)."""
    return (
        await session.scalars(
            select(TravelerDiscoverySession).where(
                TravelerDiscoverySession.destination_id == destination_id,
                TravelerDiscoverySession.visibility == DiscoveryVisibility.VISIBLE,
                TravelerDiscoverySession.user_id != exclude,
                _active(),
            )
        )
    ).all()


async def active_discovery_destination(
    session: AsyncSession, user_id: uuid.UUID
) -> uuid.UUID | None:
    found = await active_session(session, user_id)
    return found.destination_id if found else None


async def visible_discovery_destination(
    session: AsyncSession, user_id: uuid.UUID
) -> uuid.UUID | None:
    """The city the user is *visible* in. Invisible sessions count for nothing outside the
    user's own view (T-LOC-03): not even as a "shared context" for connection requests."""
    found = await active_session(session, user_id)
    if found is None or found.visibility != DiscoveryVisibility.VISIBLE:
        return None
    return found.destination_id


async def _out(
    session: AsyncSession, row: TravelerDiscoverySession, preferences: Sequence[str]
) -> DiscoverySessionOut:
    ids = [row.destination_id] + ([row.area_destination_id] if row.area_destination_id else [])
    summaries = await destinations.summaries_by_id(session, ids, preferences)
    return DiscoverySessionOut.model_validate(
        {
            "id": row.id,
            "destination": summaries[row.destination_id],
            "area": summaries.get(row.area_destination_id) if row.area_destination_id else None,
            "granularity": "neighborhood" if row.area_destination_id else "city",
            "source": row.source,
            "visibility": row.visibility,
            "travel_start_date": row.travel_start_date,
            "travel_end_date": row.travel_end_date,
            "started_at": row.started_at,
            "expires_at": row.expires_at,
        }
    )


def _invalid(field: str, message: str) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_FAILED,
        message,
        errors=[FieldError(field=field, code="invalid", message=message)],
    )


class DiscoverySessionService:
    def __init__(self, *, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def get(self, user_id: uuid.UUID, *, preferences: Sequence[str]) -> DiscoverySessionOut:
        async with self._sessionmaker() as session:
            row = await active_session(session, user_id)
            if row is None:
                raise AppError(ErrorCode.NOT_FOUND, "No active discovery session.")
            return await _out(session, row, preferences)

    async def start(
        self,
        user_id: uuid.UUID,
        request: DiscoveryByDestinationRequest | DiscoveryByGpsRequest,
        *,
        preferences: Sequence[str],
    ) -> DiscoverySessionOut:
        async with self._sessionmaker() as session, session.begin():
            settings = await require_discovery(session, user_id)
            started_today = await session.scalar(
                select(func.count())
                .select_from(TravelerDiscoverySession)
                .where(
                    TravelerDiscoverySession.user_id == user_id,
                    TravelerDiscoverySession.started_at > func.now() - timedelta(days=1),
                )
            )
            if (started_today or 0) >= DAILY_SWITCH_LIMIT:
                raise AppError(
                    ErrorCode.RATE_LIMITED,
                    "You've changed your discovery location many times today. Try again tomorrow.",
                    headers={"Retry-After": "3600"},
                )
            if isinstance(request, DiscoveryByGpsRequest):
                destinations.ensure_fresh_fix(
                    request.point.captured_at, datetime.now(tz=UTC), field="/point/captured_at"
                )
                resolved = await destinations.resolve_point(
                    session, request.point.lat, request.point.lng
                )
                if resolved is None:
                    raise AppError(
                        ErrorCode.LOCATION_UNRESOLVABLE,
                        "We don't cover this area for discovery yet.",
                    )
                city = await destinations.city_of(session, resolved)
                is_area = await destinations.kind_of(session, resolved) == "neighborhood"
                # A coarse reading can't place anyone in a neighbourhood (LOC-008).
                precise = not destinations.city_level_only(request.point.accuracy_m)
                area = resolved if resolved != city and is_area and precise else None
                source = DiscoverySource.GPS_RESOLVED
            else:
                kind = await destinations.kind_of(session, request.destination_id)
                if kind is None:
                    raise AppError(ErrorCode.NOT_FOUND, "Destination not found.")
                city = await destinations.city_of(session, request.destination_id)
                area = (
                    request.destination_id
                    if kind == "neighborhood"
                    else request.area_destination_id
                )
                if area is not None:
                    ancestry = await destinations.ancestry(session, area) or []
                    if (
                        city not in ancestry
                        or await destinations.kind_of(session, area) != "neighborhood"
                    ):
                        raise _invalid(
                            "/area_destination_id", "Choose a neighborhood of this city."
                        )
                source = DiscoverySource.MANUAL
            if settings.granularity != "neighborhood":
                area = None  # city-level presence only, unless the user chose neighborhoods
            now = await session.scalar(select(func.now()))
            assert isinstance(now, datetime)
            await session.execute(
                update(TravelerDiscoverySession)
                .where(
                    TravelerDiscoverySession.user_id == user_id,
                    TravelerDiscoverySession.ended_at.is_(None),
                )
                .values(ended_at=now)
            )
            row = TravelerDiscoverySession(
                user_id=user_id,
                destination_id=city,
                area_destination_id=area,
                source=source,
                visibility=request.visibility,
                travel_start_date=request.travel_start_date,
                travel_end_date=request.travel_end_date,
                started_at=now,
                expires_at=now + timedelta(hours=request.duration_hours),
            )
            session.add(row)
            await session.flush()
            return await _out(session, row, preferences)

    async def end(self, user_id: uuid.UUID) -> None:
        """Idempotent (DISC-002)."""
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                update(TravelerDiscoverySession)
                .where(
                    TravelerDiscoverySession.user_id == user_id,
                    TravelerDiscoverySession.ended_at.is_(None),
                )
                .values(ended_at=func.now())
            )


async def session_hops_since(
    session: AsyncSession, *, hours: int, at_least_cities: int
) -> dict[uuid.UUID, tuple[int, int]]:
    """Users who started discovery in ``at_least_cities`` cities in the window: (starts, cities)."""
    cities = func.count(func.distinct(TravelerDiscoverySession.destination_id))
    rows = await session.execute(
        select(TravelerDiscoverySession.user_id, func.count(), cities)
        .where(TravelerDiscoverySession.started_at > func.now() - timedelta(hours=hours))
        .group_by(TravelerDiscoverySession.user_id)
        .having(cities >= at_least_cities)
    )
    return {user: (starts, distinct) for user, starts, distinct in rows.all()}


async def purge_expired(session: AsyncSession) -> int:
    """Sessions are purged 30 days after they ended or expired (docs/04 §14)."""
    cutoff = platform.ago(days=30)
    return await platform.delete_batch(
        session,
        TravelerDiscoverySession,
        (TravelerDiscoverySession.ended_at < cutoff)
        | (TravelerDiscoverySession.expires_at < cutoff),
    )
