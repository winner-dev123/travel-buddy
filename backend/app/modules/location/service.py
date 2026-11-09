"""Public interface of the location module: browse and upcoming destinations (BL-1.07).

LOC-002: browsing any destination needs no GPS. Choosing one never changes discovery
visibility. Upcoming destinations may be shared for "travelers going to X" only with a
traveler-discovery consent.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode, FieldError
from app.modules.destinations import service as destinations
from app.modules.destinations.schemas import DestinationSummary
from app.modules.location.models import SelectionKind, UserSelectedLocation
from app.modules.location.schemas import (
    BrowseDestination,
    CreateUpcomingDestinationRequest,
    UpcomingDestination,
    UpcomingDestinationList,
)
from app.modules.profiles import service as profiles

MAX_UPCOMING = 20


def _destination_not_found() -> AppError:
    return AppError(ErrorCode.NOT_FOUND, "Destination not found.")


async def browse_destination_summary(
    session: AsyncSession, user_id: uuid.UUID, preferences: Sequence[str]
) -> DestinationSummary | None:
    """For ``GET /v1/users/me`` (wired into identity by the composition root)."""
    selection = await _browse_row(session, user_id)
    if selection is None:
        return None
    found = await destinations.summaries_by_id(session, [selection.destination_id], preferences)
    return found.get(selection.destination_id)


async def _browse_row(session: AsyncSession, user_id: uuid.UUID) -> UserSelectedLocation | None:
    row: UserSelectedLocation | None = await session.scalar(
        select(UserSelectedLocation).where(
            UserSelectedLocation.user_id == user_id,
            UserSelectedLocation.kind == SelectionKind.BROWSE,
        )
    )
    return row


class LocationService:
    def __init__(self, *, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    # ─────────────────────────────── browse ───────────────────────────────

    async def get_browse(
        self, user_id: uuid.UUID, *, preferences: Sequence[str]
    ) -> BrowseDestination:
        async with self._sessionmaker() as session:
            row = await _browse_row(session, user_id)
            summary = (
                (
                    await destinations.summaries_by_id(session, [row.destination_id], preferences)
                ).get(row.destination_id)
                if row
                else None
            )
            if row is None or summary is None:  # none chosen, or the destination was hidden
                raise AppError(ErrorCode.NOT_FOUND, "No browse destination selected.")
            return BrowseDestination(destination=summary, selected_at=row.created_at)

    async def set_browse(
        self, user_id: uuid.UUID, destination_id: uuid.UUID, *, preferences: Sequence[str]
    ) -> BrowseDestination:
        for attempt in range(2):  # a concurrent PUT may win the one-browse unique index
            try:
                async with self._sessionmaker() as session, session.begin():
                    if not await destinations.is_active(session, destination_id):
                        raise _destination_not_found()
                    row = await _browse_row(session, user_id)
                    if row is None:
                        row = UserSelectedLocation(
                            user_id=user_id,
                            destination_id=destination_id,
                            kind=SelectionKind.BROWSE,
                        )
                        session.add(row)
                    elif row.destination_id != destination_id:
                        row.destination_id = destination_id
                        row.created_at = func.now()
                    await session.flush()
                    await session.refresh(row)
                    summary = (
                        await destinations.summaries_by_id(session, [destination_id], preferences)
                    )[destination_id]
                    return BrowseDestination(destination=summary, selected_at=row.created_at)
            except IntegrityError:
                if attempt == 1:
                    raise
        raise AssertionError("unreachable")  # pragma: no cover

    async def clear_browse(self, user_id: uuid.UUID) -> None:
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                delete(UserSelectedLocation).where(
                    UserSelectedLocation.user_id == user_id,
                    UserSelectedLocation.kind == SelectionKind.BROWSE,
                )
            )

    # ─────────────────────────────── upcoming ───────────────────────────────

    async def list_upcoming(
        self, user_id: uuid.UUID, *, preferences: Sequence[str]
    ) -> UpcomingDestinationList:
        async with self._sessionmaker() as session:
            rows = (
                await session.scalars(
                    select(UserSelectedLocation)
                    .where(
                        UserSelectedLocation.user_id == user_id,
                        UserSelectedLocation.kind == SelectionKind.UPCOMING,
                    )
                    .order_by(
                        UserSelectedLocation.start_date.asc().nulls_last(),
                        UserSelectedLocation.created_at,
                    )
                )
            ).all()
            summaries = await destinations.summaries_by_id(
                session, [r.destination_id for r in rows], preferences
            )
        return UpcomingDestinationList(
            data=[
                _upcoming(r, summaries[r.destination_id])
                for r in rows
                if r.destination_id in summaries
            ]
        )

    async def add_upcoming(
        self,
        user_id: uuid.UUID,
        request: CreateUpcomingDestinationRequest,
        *,
        preferences: Sequence[str],
    ) -> UpcomingDestination:
        if request.start_date and request.end_date and request.end_date < request.start_date:
            raise AppError(
                ErrorCode.VALIDATION_FAILED,
                "The trip cannot end before it starts.",
                errors=[
                    FieldError(field="/end_date", code="before_start", message="Before start_date.")
                ],
            )
        try:
            async with self._sessionmaker() as session, session.begin():
                if not await destinations.is_active(session, request.destination_id):
                    raise _destination_not_found()
                if request.share_for_discovery and not await profiles.has_discovery_consent(
                    session, user_id
                ):
                    raise AppError(
                        ErrorCode.CONSENT_REQUIRED,
                        "Sharing upcoming trips with other travelers needs your consent first.",
                        extensions={"consent_type": "traveler_discovery"},
                    )
                count = await session.scalar(
                    select(func.count())
                    .select_from(UserSelectedLocation)
                    .where(
                        UserSelectedLocation.user_id == user_id,
                        UserSelectedLocation.kind == SelectionKind.UPCOMING,
                    )
                )
                if (count or 0) >= MAX_UPCOMING:
                    raise AppError(
                        ErrorCode.VALIDATION_FAILED,
                        f"You can keep up to {MAX_UPCOMING} upcoming destinations.",
                        errors=[
                            FieldError(field="/destination_id", code="limit_reached", message="")
                        ],
                    )
                row = UserSelectedLocation(
                    user_id=user_id,
                    destination_id=request.destination_id,
                    kind=SelectionKind.UPCOMING,
                    start_date=request.start_date,
                    end_date=request.end_date,
                    share_for_discovery=request.share_for_discovery,
                )
                session.add(row)
                await session.flush()
                await session.refresh(row)
                summary = (
                    await destinations.summaries_by_id(
                        session, [request.destination_id], preferences
                    )
                )[request.destination_id]
                return _upcoming(row, summary)
        except IntegrityError as exc:
            raise AppError(
                ErrorCode.CONFLICT, "This destination is already in your upcoming list."
            ) from exc

    async def remove_upcoming(self, user_id: uuid.UUID, selection_id: uuid.UUID) -> None:
        async with self._sessionmaker() as session, session.begin():
            result = await session.execute(
                delete(UserSelectedLocation)
                .where(
                    UserSelectedLocation.id == selection_id,
                    UserSelectedLocation.user_id == user_id,
                    UserSelectedLocation.kind == SelectionKind.UPCOMING,
                )
                .returning(UserSelectedLocation.id)
            )
            if result.first() is None:
                raise AppError(ErrorCode.NOT_FOUND, "Upcoming destination not found.")


def _upcoming(row: UserSelectedLocation, summary: DestinationSummary) -> UpcomingDestination:
    return UpcomingDestination(
        id=row.id,
        destination=summary,
        start_date=row.start_date,
        end_date=row.end_date,
        share_for_discovery=row.share_for_discovery,
        created_at=row.created_at,
    )
