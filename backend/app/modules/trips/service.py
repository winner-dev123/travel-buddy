"""Trips and itineraries (BL-4.04; TRIP-001, TRIP-004, TRIP-005).

- A trip belongs to its owner; collaborators are editors or viewers. Private trips are visible to
  them only, public trips to every signed-in traveller (``connections`` and ``group`` visibility
  arrive with their modules and answer ``feature_disabled`` until then).
- Every change bumps ``version``; REST edits need ``If-Match`` (``428``/``412``).
- Items keep a fractional ``sort_order`` (one row per move) and tombstones (``deleted_at``) so an
  offline client can sync. ``POST /sync`` applies a batch: for each entity, the newer write wins;
  when the server changed it after the client's base and later than the client's edit, the
  operation comes back as a conflict with the server's state instead (TRIP-004).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal

from pydantic import ValidationError
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.pagination import CursorCodec, PageInfo
from app.core.security.principal import Principal
from app.core.time import Clock
from app.modules.destinations import service as destinations
from app.modules.platform import service as platform
from app.modules.profiles import service as profiles
from app.modules.trips.models import (
    ItineraryDay,
    ItineraryItem,
    Trip,
    TripCollaborator,
    TripDestination,
)
from app.modules.trips.schemas import (
    CollaboratorOut,
    CreateTripRequest,
    DayInput,
    DayOut,
    ItemInput,
    ItemOut,
    ItemPatch,
    SourceAttribution,
    SyncConflict,
    SyncOperation,
    SyncRequest,
    SyncResult,
    TripDestinationOut,
    TripOut,
    TripSummary,
    TripSummaryPage,
    UpdateTripRequest,
)

CREATE_ROUTE = "POST /v1/trips"
ConflictReason = Literal["modified_on_server", "deleted_on_server", "invalid"]
SYNC_ROUTE = "POST /v1/trips/{id}/sync"
SUPPORTED_VISIBILITY = ("private", "public")
MAX_DAYS = 90


def _not_found(what: str = "Trip") -> AppError:
    return AppError(ErrorCode.NOT_FOUND, f"{what} not found.")


def _invalid(field: str, message: str) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_FAILED,
        message,
        errors=[FieldError(field=field, code="invalid", message=message)],
    )


def _check_version(current: int, if_match: str | None) -> None:
    if if_match is None:
        raise AppError(ErrorCode.PRECONDITION_REQUIRED, "Send If-Match with the trip version.")
    if if_match.strip().strip('"') != str(current):
        raise AppError(
            ErrorCode.PRECONDITION_FAILED, "This trip changed elsewhere. Reload and try again."
        )


def _visibility(value: str | None) -> None:
    if value is not None and value not in SUPPORTED_VISIBILITY:
        raise AppError(ErrorCode.FEATURE_DISABLED, "Trips can be private or public for now.")


def _hhmm(value: str | None) -> time | None:
    if value is None:
        return None
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def _item_state(item: ItineraryItem) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "day_id": str(item.day_id),
        "kind": item.kind,
        "title": item.title,
        "notes": item.notes,
        "start_time": item.start_time.strftime("%H:%M") if item.start_time else None,
        "duration_minutes": item.duration_minutes,
        "sort_order": str(item.sort_order),
        "deleted": item.deleted_at is not None,
        "updated_at": item.updated_at.isoformat(),
    }


class TripService:
    def __init__(
        self, *, sessionmaker: async_sessionmaker[AsyncSession], cursors: CursorCodec, clock: Clock
    ) -> None:
        self._sessionmaker = sessionmaker
        self._cursors = cursors
        self._clock = clock

    # ─────────────────────────────── access ───────────────────────────────

    async def _load(
        self,
        session: AsyncSession,
        trip_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        write: bool = False,
        lock: bool = False,
    ) -> tuple[Trip, str | None]:
        trip = await session.get(Trip, trip_id, with_for_update=lock)
        if trip is None or trip.deleted_at is not None:
            raise _not_found()
        role: str | None = "owner" if trip.owner_id == user_id else None
        if role is None:
            role = await session.scalar(
                select(TripCollaborator.role).where(
                    TripCollaborator.trip_id == trip_id, TripCollaborator.user_id == user_id
                )
            )
        if role is None and trip.visibility != "public":
            raise _not_found()
        if write and role not in ("owner", "editor"):
            raise AppError(ErrorCode.FORBIDDEN, "You can view this trip but not edit it.")
        return trip, role

    def _touch(self, trip: Trip) -> None:
        trip.version += 1
        trip.updated_at = self._clock.now()

    # ─────────────────────────────── output ───────────────────────────────

    async def _out(self, session: AsyncSession, trip: Trip, locale: str = "en") -> TripOut:
        stops = list(
            await session.scalars(
                select(TripDestination)
                .where(TripDestination.trip_id == trip.id)
                .order_by(TripDestination.sort_order)
            )
        )
        days = list(
            await session.scalars(
                select(ItineraryDay)
                .where(ItineraryDay.trip_id == trip.id)
                .order_by(ItineraryDay.day_index)
            )
        )
        items = (
            list(
                await session.scalars(
                    select(ItineraryItem)
                    .where(
                        ItineraryItem.day_id.in_([d.id for d in days]),
                        ItineraryItem.deleted_at.is_(None),
                    )
                    .order_by(ItineraryItem.sort_order)
                )
            )
            if days
            else []
        )
        places = await destinations.summaries_by_id(
            session,
            list(
                {s.destination_id for s in stops}
                | {d.destination_id for d in days if d.destination_id}
            ),
            [locale],
        )
        collaborators = list(
            await session.scalars(
                select(TripCollaborator).where(TripCollaborator.trip_id == trip.id)
            )
        )
        users = await profiles.authors(
            session, [trip.owner_id, *[c.user_id for c in collaborators]]
        )
        by_day: dict[uuid.UUID, list[ItemOut]] = {d.id: [] for d in days}
        for item in items:
            by_day[item.day_id].append(
                ItemOut(
                    id=item.id,
                    sort_order=format(item.sort_order.normalize(), "f"),
                    kind=item.kind,  # type: ignore[arg-type]
                    title=item.title,
                    notes=item.notes,
                    start_time=item.start_time.strftime("%H:%M") if item.start_time else None,
                    duration_minutes=item.duration_minutes,
                    origin=item.origin,  # type: ignore[arg-type]
                    ai_confidence=float(item.ai_confidence)
                    if item.ai_confidence is not None
                    else None,
                    unverified=item.unverified,
                    source_attribution=[
                        SourceAttribution.model_validate(a) for a in item.source_attribution
                    ],
                    data_freshness_at=item.data_freshness_at,
                    updated_at=item.updated_at,
                )
            )
        owner = users.get(trip.owner_id)
        assert owner is not None
        return TripOut(
            id=trip.id,
            owner=profiles.user_summary(owner),
            title=trip.title,
            start_date=trip.start_date,
            end_date=trip.end_date,
            visibility=trip.visibility,  # type: ignore[arg-type]
            group_id=trip.group_id,
            origin=trip.origin,  # type: ignore[arg-type]
            status=trip.status,  # type: ignore[arg-type]
            destinations=[
                TripDestinationOut(
                    destination=places[s.destination_id],
                    start_date=s.start_date,
                    end_date=s.end_date,
                    sort_order=s.sort_order,
                )
                for s in stops
                if s.destination_id in places
            ],
            days=[
                DayOut(
                    id=d.id,
                    day_index=d.day_index,
                    date=d.date,
                    destination=places.get(d.destination_id) if d.destination_id else None,
                    notes=d.notes,
                    items=by_day[d.id],
                )
                for d in days
            ],
            collaborators=[
                CollaboratorOut(user=profiles.user_summary(users[c.user_id]), role=c.role)  # type: ignore[arg-type]
                for c in collaborators
                if c.user_id in users
            ],
            version=trip.version,
            created_at=trip.created_at,
            updated_at=trip.updated_at,
        )

    # ─────────────────────────────── trips ───────────────────────────────

    async def _set_destinations(
        self, session: AsyncSession, trip: Trip, destination_ids: Sequence[uuid.UUID]
    ) -> None:
        unique = list(dict.fromkeys(destination_ids))
        for index, destination_id in enumerate(unique):
            if not await destinations.is_active(session, destination_id):
                raise _invalid(f"/destination_ids/{index}", "Pick destinations from the list.")
        await session.execute(delete(TripDestination).where(TripDestination.trip_id == trip.id))
        session.add_all(
            [
                TripDestination(trip_id=trip.id, destination_id=d, sort_order=i)
                for i, d in enumerate(unique)
            ]
        )

    async def create(
        self, principal: Principal, request: CreateTripRequest, *, idempotency_key: uuid.UUID
    ) -> TripOut:
        _visibility(request.visibility)
        if request.group_id is not None:
            raise AppError(ErrorCode.FEATURE_DISABLED, "Group trips arrive later.")
        if (request.end_date - request.start_date).days >= MAX_DAYS:
            raise _invalid("/end_date", f"Trips can last up to {MAX_DAYS} days.")
        async with self._sessionmaker() as session, session.begin():
            replay = await platform.idempotency.claim(
                session,
                user_id=principal.user_id,
                key=idempotency_key,
                route=CREATE_ROUTE,
                payload=request.model_dump(mode="json"),
            )
            if replay is not None:
                return TripOut.model_validate(replay.body)
            trip = Trip(
                owner_id=principal.user_id,
                title=request.title.strip(),
                start_date=request.start_date,
                end_date=request.end_date,
                visibility=request.visibility,
                updated_at=self._clock.now(),
            )
            session.add(trip)
            await session.flush()
            await self._set_destinations(session, trip, request.destination_ids)
            # One day per date, so the editor starts with a skeleton (TRIP-001).
            length = (request.end_date - request.start_date).days + 1
            session.add_all(
                [
                    ItineraryDay(
                        trip_id=trip.id,
                        day_index=i,
                        date=request.start_date + timedelta(days=i),
                        destination_id=request.destination_ids[0]
                        if request.destination_ids
                        else None,
                    )
                    for i in range(length)
                ]
            )
            await session.flush()
            await session.refresh(trip)
            out = await self._out(session, trip)
            await platform.idempotency.complete(
                session,
                user_id=principal.user_id,
                key=idempotency_key,
                status=201,
                body=out.model_dump(mode="json"),
            )
        return out

    async def list_mine(
        self, user_id: uuid.UUID, *, status: str | None, cursor: str | None, limit: int
    ) -> TripSummaryPage:
        scope = f"trips.{user_id}.{status or 'all'}"
        shared = select(TripCollaborator.trip_id).where(TripCollaborator.user_id == user_id)
        conditions = [
            Trip.deleted_at.is_(None),
            or_(Trip.owner_id == user_id, Trip.id.in_(shared)),
        ]
        if status:
            conditions.append(Trip.status == status)
        if cursor:
            position = self._cursors.decode(cursor, scope=scope)
            conditions.append(Trip.id < uuid.UUID(str(position["id"])))
        async with self._sessionmaker() as session:
            trips = list(
                await session.scalars(
                    select(Trip).where(*conditions).order_by(Trip.id.desc()).limit(limit + 1)
                )
            )
            has_more = len(trips) > limit
            trips = trips[:limit]
            roles = (
                dict(
                    (
                        await session.execute(
                            select(TripCollaborator.trip_id, TripCollaborator.role).where(
                                TripCollaborator.user_id == user_id,
                                TripCollaborator.trip_id.in_([t.id for t in trips]),
                            )
                        )
                    )
                    .tuples()
                    .all()
                )
                if trips
                else {}
            )
            stops = (
                (
                    await session.execute(
                        select(TripDestination.trip_id, TripDestination.destination_id)
                        .where(TripDestination.trip_id.in_([t.id for t in trips]))
                        .order_by(TripDestination.sort_order)
                    )
                )
                .tuples()
                .all()
                if trips
                else []
            )
            places = await destinations.summaries_by_id(
                session, list({d for _, d in stops}), ["en"]
            )
        by_trip: dict[uuid.UUID, list[Any]] = {}
        for trip_id, destination_id in stops:
            if destination_id in places:
                by_trip.setdefault(trip_id, []).append(places[destination_id])
        next_cursor = (
            self._cursors.encode({"id": str(trips[-1].id)}, scope=scope)
            if has_more and trips
            else None
        )
        return TripSummaryPage(
            data=[
                TripSummary(
                    id=t.id,
                    title=t.title,
                    start_date=t.start_date,
                    end_date=t.end_date,
                    status=t.status,  # type: ignore[arg-type]
                    visibility=t.visibility,  # type: ignore[arg-type]
                    origin=t.origin,  # type: ignore[arg-type]
                    destinations=by_trip.get(t.id, []),
                    role="owner" if t.owner_id == user_id else roles.get(t.id, "viewer"),  # type: ignore[arg-type]
                    updated_at=t.updated_at,
                )
                for t in trips
            ],
            page=PageInfo(next_cursor=next_cursor, has_more=has_more),
        )

    async def get(self, user_id: uuid.UUID, trip_id: uuid.UUID) -> TripOut:
        async with self._sessionmaker() as session:
            trip, _ = await self._load(session, trip_id, user_id)
            return await self._out(session, trip)

    async def update(
        self,
        user_id: uuid.UUID,
        trip_id: uuid.UUID,
        request: UpdateTripRequest,
        *,
        if_match: str | None,
    ) -> TripOut:
        async with self._sessionmaker() as session, session.begin():
            trip, _ = await self._load(session, trip_id, user_id, write=True, lock=True)
            _check_version(trip.version, if_match)
            await self._apply_trip(session, trip, request)
            self._touch(trip)
            await session.flush()
            return await self._out(session, trip)

    async def _apply_trip(
        self, session: AsyncSession, trip: Trip, request: UpdateTripRequest
    ) -> None:
        changes = request.model_dump(exclude_unset=True)
        _visibility(changes.get("visibility"))
        if changes.get("group_id") is not None:
            raise AppError(ErrorCode.FEATURE_DISABLED, "Group trips arrive later.")
        start = changes.get("start_date", trip.start_date)
        end = changes.get("end_date", trip.end_date)
        if start > end:
            raise _invalid("/end_date", "The end date must be on or after the start date.")
        for field in ("title", "start_date", "end_date", "visibility", "status"):
            if field in changes and changes[field] is not None:
                setattr(trip, field, changes[field].strip() if field == "title" else changes[field])
        if changes.get("destination_ids") is not None:
            await self._set_destinations(session, trip, changes["destination_ids"])

    async def delete(self, user_id: uuid.UUID, trip_id: uuid.UUID) -> None:
        async with self._sessionmaker() as session, session.begin():
            trip, role = await self._load(session, trip_id, user_id, write=True, lock=True)
            if role != "owner":
                raise AppError(ErrorCode.FORBIDDEN, "Only the owner can delete the trip.")
            trip.deleted_at = self._clock.now()
            self._touch(trip)

    # ─────────────────────────────── days ───────────────────────────────

    async def _day(self, session: AsyncSession, trip: Trip, day_id: uuid.UUID) -> ItineraryDay:
        day = await session.get(ItineraryDay, day_id)
        if day is None or day.trip_id != trip.id:
            raise _not_found("Day")
        return day

    async def _apply_day(
        self, session: AsyncSession, trip: Trip, day: ItineraryDay, request: DayInput
    ) -> None:
        changes = request.model_dump(exclude_unset=True)
        place = changes.get("destination_id")
        if place is not None and not await destinations.is_active(session, place):
            raise _invalid("/destination_id", "Pick a destination from the list.")
        if changes.get("day_index") is not None and changes["day_index"] != day.day_index:
            taken = await session.scalar(
                select(func.count())
                .select_from(ItineraryDay)
                .where(
                    ItineraryDay.trip_id == trip.id, ItineraryDay.day_index == changes["day_index"]
                )
            )
            if taken:
                raise _invalid("/day_index", "That day already exists.")
        for field in ("day_index", "date", "destination_id", "notes"):
            if field in changes:
                if field == "day_index" and changes[field] is None:
                    continue
                setattr(day, field, changes[field])
        day.updated_at = self._clock.now()

    async def add_day(
        self, user_id: uuid.UUID, trip_id: uuid.UUID, request: DayInput, *, if_match: str | None
    ) -> TripOut:
        async with self._sessionmaker() as session, session.begin():
            trip, _ = await self._load(session, trip_id, user_id, write=True, lock=True)
            _check_version(trip.version, if_match)
            last = await session.scalar(
                select(func.max(ItineraryDay.day_index)).where(ItineraryDay.trip_id == trip.id)
            )
            index = (
                request.day_index
                if request.day_index is not None
                else (last + 1 if last is not None else 0)
            )
            day = ItineraryDay(trip_id=trip.id, day_index=index)
            session.add(day)
            await self._apply_day(
                session, trip, day, request.model_copy(update={"day_index": None})
            )
            day.day_index = index
            if day.date is None:
                day.date = trip.start_date + timedelta(days=index)
            self._touch(trip)
            await session.flush()
            return await self._out(session, trip)

    async def update_day(
        self,
        user_id: uuid.UUID,
        trip_id: uuid.UUID,
        day_id: uuid.UUID,
        request: DayInput,
        *,
        if_match: str | None,
    ) -> TripOut:
        async with self._sessionmaker() as session, session.begin():
            trip, _ = await self._load(session, trip_id, user_id, write=True, lock=True)
            _check_version(trip.version, if_match)
            await self._apply_day(session, trip, await self._day(session, trip, day_id), request)
            self._touch(trip)
            await session.flush()
            return await self._out(session, trip)

    async def delete_day(
        self, user_id: uuid.UUID, trip_id: uuid.UUID, day_id: uuid.UUID, *, if_match: str | None
    ) -> TripOut:
        async with self._sessionmaker() as session, session.begin():
            trip, _ = await self._load(session, trip_id, user_id, write=True, lock=True)
            _check_version(trip.version, if_match)
            await session.delete(await self._day(session, trip, day_id))
            self._touch(trip)
            await session.flush()
            return await self._out(session, trip)

    # ─────────────────────────────── items ───────────────────────────────

    async def _order_after(
        self,
        session: AsyncSession,
        day_id: uuid.UUID,
        after_item_id: uuid.UUID | None,
        *,
        exclude: uuid.UUID | None = None,
    ) -> Decimal:
        """A fractional position after ``after_item_id`` (``None``: at the end of the day)."""
        live = [
            ItineraryItem.day_id == day_id,
            ItineraryItem.deleted_at.is_(None),
        ]
        if exclude is not None:
            live.append(ItineraryItem.id != exclude)
        if after_item_id is None:
            last = await session.scalar(select(func.max(ItineraryItem.sort_order)).where(*live))
            return (last or Decimal(0)) + 1
        anchor = await session.get(ItineraryItem, after_item_id)
        if anchor is None or anchor.day_id != day_id or anchor.deleted_at is not None:
            raise _invalid("/after_item_id", "That item isn't in this day.")
        following = await session.scalar(
            select(func.min(ItineraryItem.sort_order)).where(
                *live, ItineraryItem.sort_order > anchor.sort_order
            )
        )
        return anchor.sort_order + 1 if following is None else (anchor.sort_order + following) / 2

    async def _item(self, session: AsyncSession, trip: Trip, item_id: uuid.UUID) -> ItineraryItem:
        item = await session.get(ItineraryItem, item_id)
        if item is not None:
            day = await session.get(ItineraryDay, item.day_id)
            if day is not None and day.trip_id == trip.id and item.deleted_at is None:
                return item
        raise _not_found("Item")

    async def _create_item(
        self,
        session: AsyncSession,
        trip: Trip,
        day: ItineraryDay,
        request: ItemInput,
        *,
        item_id: uuid.UUID | None = None,
        client_updated_at: datetime | None = None,
    ) -> ItineraryItem:
        item = ItineraryItem(
            day_id=day.id,
            sort_order=await self._order_after(session, day.id, request.after_item_id),
            kind=request.kind,
            place_id=request.place_id,
            title=request.title.strip(),
            notes=request.notes,
            start_time=_hhmm(request.start_time),
            duration_minutes=request.duration_minutes,
            client_updated_at=client_updated_at,
            updated_at=self._clock.now(),
        )
        if item_id is not None:
            item.id = item_id
        session.add(item)
        await session.flush()
        return item

    async def _patch_item(
        self, session: AsyncSession, trip: Trip, item: ItineraryItem, request: ItemPatch
    ) -> None:
        changes = request.model_dump(exclude_unset=True)
        if "day_id" in changes or "after_item_id" in changes:
            day_id = changes.get("day_id") or item.day_id
            day = await self._day(session, trip, day_id)
            item.day_id = day.id
            item.sort_order = await self._order_after(
                session, day.id, changes.get("after_item_id"), exclude=item.id
            )
        for field in ("kind", "place_id", "title", "notes", "duration_minutes"):
            if field in changes:
                if field in ("kind", "title") and changes[field] is None:
                    continue
                setattr(item, field, changes[field].strip() if field == "title" else changes[field])
        if "start_time" in changes:
            item.start_time = _hhmm(changes["start_time"])
        item.updated_at = self._clock.now()

    async def add_item(
        self,
        user_id: uuid.UUID,
        trip_id: uuid.UUID,
        day_id: uuid.UUID,
        request: ItemInput,
        *,
        if_match: str | None,
    ) -> TripOut:
        async with self._sessionmaker() as session, session.begin():
            trip, _ = await self._load(session, trip_id, user_id, write=True, lock=True)
            _check_version(trip.version, if_match)
            await self._create_item(session, trip, await self._day(session, trip, day_id), request)
            self._touch(trip)
            await session.flush()
            return await self._out(session, trip)

    async def update_item(
        self,
        user_id: uuid.UUID,
        trip_id: uuid.UUID,
        item_id: uuid.UUID,
        request: ItemPatch,
        *,
        if_match: str | None,
    ) -> TripOut:
        async with self._sessionmaker() as session, session.begin():
            trip, _ = await self._load(session, trip_id, user_id, write=True, lock=True)
            _check_version(trip.version, if_match)
            await self._patch_item(session, trip, await self._item(session, trip, item_id), request)
            self._touch(trip)
            await session.flush()
            return await self._out(session, trip)

    async def delete_item(
        self, user_id: uuid.UUID, trip_id: uuid.UUID, item_id: uuid.UUID, *, if_match: str | None
    ) -> TripOut:
        async with self._sessionmaker() as session, session.begin():
            trip, _ = await self._load(session, trip_id, user_id, write=True, lock=True)
            _check_version(trip.version, if_match)
            item = await self._item(session, trip, item_id)
            item.deleted_at = item.updated_at = self._clock.now()  # tombstone for offline sync
            self._touch(trip)
            await session.flush()
            return await self._out(session, trip)

    # ─────────────────────────────── offline sync ───────────────────────────────

    async def sync(
        self,
        principal: Principal,
        trip_id: uuid.UUID,
        request: SyncRequest,
        *,
        idempotency_key: uuid.UUID,
    ) -> SyncResult:
        """Apply an offline batch (TRIP-004): newer writes win; edits the server made after the
        client's base and later than the client's come back as conflicts."""
        async with self._sessionmaker() as session, session.begin():
            replay = await platform.idempotency.claim(
                session,
                user_id=principal.user_id,
                key=idempotency_key,
                route=SYNC_ROUTE,
                payload={"trip": str(trip_id), **request.model_dump(mode="json")},
            )
            if replay is not None:
                return SyncResult.model_validate(replay.body)
            trip, _ = await self._load(session, trip_id, principal.user_id, write=True, lock=True)
            stale = trip.version > request.base_version
            applied: list[uuid.UUID] = []
            conflicts: list[SyncConflict] = []
            for op in request.operations:
                try:
                    async with session.begin_nested():
                        outcome = await self._apply_op(session, trip, op, stale=stale)
                except (AppError, ValidationError):
                    outcome = SyncConflict(
                        op_id=op.op_id,
                        entity=op.entity,
                        entity_id=op.entity_id,
                        reason="invalid",
                        server_state=None,
                    )
                if outcome is None:
                    applied.append(op.op_id)
                else:
                    conflicts.append(outcome)
            if applied:
                self._touch(trip)
                await session.flush()
            result = SyncResult(
                trip=await self._out(session, trip), applied_op_ids=applied, conflicts=conflicts
            )
            await platform.idempotency.complete(
                session,
                user_id=principal.user_id,
                key=idempotency_key,
                status=200,
                body=result.model_dump(mode="json"),
            )
        return result

    async def _apply_op(
        self, session: AsyncSession, trip: Trip, op: SyncOperation, *, stale: bool
    ) -> SyncConflict | None:
        def conflict(reason: ConflictReason, state: dict[str, Any] | None) -> SyncConflict:
            return SyncConflict(
                op_id=op.op_id,
                entity=op.entity,
                entity_id=op.entity_id,
                reason=reason,
                server_state=state,
            )

        if op.entity == "item":
            item = await session.get(ItineraryItem, op.entity_id)
            if item is not None:
                day = await session.get(ItineraryDay, item.day_id)
                if day is None or day.trip_id != trip.id:
                    return conflict("invalid", None)
            if op.action == "create" and item is None:
                if op.parent_id is None:
                    return conflict("invalid", None)
                day = await self._day(session, trip, op.parent_id)
                await self._create_item(
                    session,
                    trip,
                    day,
                    ItemInput.model_validate(op.fields),
                    item_id=op.entity_id,
                    client_updated_at=op.client_updated_at,
                )
                return None
            if item is None:
                return None if op.action == "delete" else conflict("deleted_on_server", None)
            if item.deleted_at is not None:
                return (
                    None
                    if op.action == "delete"
                    else conflict("deleted_on_server", _item_state(item))
                )
            patch = None
            if op.action != "delete":  # invalid edits are reported as such, before anything else
                patch = ItemPatch.model_validate(
                    op.fields
                    if op.action == "update"
                    else {k: v for k, v in op.fields.items() if k in ItemPatch.model_fields}
                )
            if stale and item.updated_at > op.client_updated_at:
                return conflict("modified_on_server", _item_state(item))
            if patch is None:
                item.deleted_at = item.updated_at = self._clock.now()
                return None
            await self._patch_item(session, trip, item, patch)
            item.client_updated_at = op.client_updated_at
            return None
        if op.entity == "day":
            day = await session.get(ItineraryDay, op.entity_id)
            if day is not None and day.trip_id != trip.id:
                return conflict("invalid", None)
            if op.action == "create" and day is None:
                created = ItineraryDay(id=op.entity_id, trip_id=trip.id, day_index=0)
                payload = DayInput.model_validate(op.fields)
                last = await session.scalar(
                    select(func.max(ItineraryDay.day_index)).where(ItineraryDay.trip_id == trip.id)
                )
                created.day_index = (
                    payload.day_index
                    if payload.day_index is not None
                    else (last + 1 if last is not None else 0)
                )
                session.add(created)
                await self._apply_day(
                    session, trip, created, payload.model_copy(update={"day_index": None})
                )
                await session.flush()
                return None
            if day is None:
                return None if op.action == "delete" else conflict("deleted_on_server", None)
            if stale and day.updated_at > op.client_updated_at:
                return conflict(
                    "modified_on_server",
                    {"id": str(day.id), "day_index": day.day_index, "notes": day.notes},
                )
            if op.action == "delete":
                await session.delete(day)
                await session.flush()
                return None
            await self._apply_day(session, trip, day, DayInput.model_validate(op.fields))
            return None
        # The trip itself: updates only.
        if op.action != "update" or op.entity_id != trip.id:
            return conflict("invalid", None)
        if stale and trip.updated_at > op.client_updated_at:
            return conflict(
                "modified_on_server",
                {"title": trip.title, "status": trip.status, "version": trip.version},
            )
        await self._apply_trip(session, trip, UpdateTripRequest.model_validate(op.fields))
        return None


async def purge_expired(session: AsyncSession) -> int:
    """Deleted trips after 30 days; item tombstones after 90 days (clients have synced)."""
    trips = await platform.delete_batch(session, Trip, Trip.deleted_at < platform.ago(days=30))
    items = await platform.delete_batch(
        session, ItineraryItem, ItineraryItem.deleted_at < platform.ago(days=90)
    )
    return trips + items
