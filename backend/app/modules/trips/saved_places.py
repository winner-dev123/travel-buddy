"""Saved places (TRIP-003): ``/v1/users/me/saved-places``.

Saving is idempotent (a second save updates the note). A place can be in several named
collections. Places taken down from the catalog drop out of the list, and places removed from it
take their saves with them (``ON DELETE CASCADE``). Newest saves come first.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, literal, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode
from app.core.pagination import CursorCodec, PageInfo
from app.core.time import Clock
from app.modules.destinations import service as destinations
from app.modules.trips.models import SavedPlace
from app.modules.trips.schemas import SavedPlaceOut, SavedPlacePage, SavePlaceRequest

_SCOPE = "saved_places"
_FILTER_SCAN_MAX = 2000  # a destination filter looks at the user's newest saves only


class SavedPlaceService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        cursors: CursorCodec,
        clock: Clock,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._cursors = cursors
        self._clock = clock

    async def save(
        self,
        user_id: uuid.UUID,
        place_id: uuid.UUID,
        request: SavePlaceRequest,
        *,
        preferences: Sequence[str],
    ) -> SavedPlaceOut:
        collection = request.collection.strip() or "default"
        async with self._sessionmaker() as session, session.begin():
            if not await destinations.place_is_listed(session, place_id):
                raise AppError(ErrorCode.NOT_FOUND, "Place not found.")
            row = (
                await session.execute(
                    insert(SavedPlace)
                    .values(
                        user_id=user_id,
                        place_id=place_id,
                        collection=collection,
                        note=request.note,
                        created_at=self._clock.now(),
                    )
                    .on_conflict_do_update(
                        index_elements=[
                            SavedPlace.user_id,
                            SavedPlace.place_id,
                            SavedPlace.collection,
                        ],
                        set_={"note": request.note},
                    )
                    .returning(SavedPlace.note, SavedPlace.created_at)
                )
            ).one()
            places = await destinations.place_summaries(session, [place_id], preferences)
        return SavedPlaceOut(
            place=places[place_id], collection=collection, note=row.note, created_at=row.created_at
        )

    async def unsave(self, user_id: uuid.UUID, place_id: uuid.UUID, collection: str) -> None:
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                delete(SavedPlace).where(
                    SavedPlace.user_id == user_id,
                    SavedPlace.place_id == place_id,
                    SavedPlace.collection == collection,
                )
            )

    async def list(
        self,
        user_id: uuid.UUID,
        *,
        collection: str | None,
        destination_id: uuid.UUID | None,
        cursor: str | None,
        limit: int,
        preferences: Sequence[str],
    ) -> SavedPlacePage:
        filters = {
            "c": collection,
            "d": str(destination_id) if destination_id else None,
        }
        conditions = [SavedPlace.user_id == user_id]
        if collection is not None:
            conditions.append(SavedPlace.collection == collection)
        if cursor is not None:
            decoded = self._cursors.decode(cursor, scope=_SCOPE)
            if decoded.get("f") != filters:
                raise AppError(ErrorCode.INVALID_CURSOR, "The cursor belongs to another query.")
            conditions.append(
                tuple_(SavedPlace.created_at, SavedPlace.place_id, SavedPlace.collection)
                < tuple_(
                    literal(datetime.fromisoformat(decoded["t"])),
                    literal(uuid.UUID(decoded["p"])),
                    literal(str(decoded["k"])),
                )
            )
        async with self._sessionmaker() as session:
            if destination_id is not None:
                saved_ids = list(
                    (
                        await session.scalars(
                            select(SavedPlace.place_id)
                            .where(SavedPlace.user_id == user_id)
                            .order_by(SavedPlace.created_at.desc())
                            .limit(_FILTER_SCAN_MAX)
                        )
                    ).all()
                )
                inside = await destinations.place_ids_within(session, saved_ids, destination_id)
                conditions.append(SavedPlace.place_id.in_(inside))
            rows = list(
                (
                    await session.scalars(
                        select(SavedPlace)
                        .where(*conditions)
                        .order_by(
                            SavedPlace.created_at.desc(),
                            SavedPlace.place_id.desc(),
                            SavedPlace.collection.desc(),
                        )
                        .limit(limit + 1)
                    )
                ).all()
            )
            more = len(rows) > limit
            rows = rows[:limit]
            places = await destinations.place_summaries(
                session, list({row.place_id for row in rows}), preferences
            )
        data = [
            SavedPlaceOut(
                place=places[row.place_id],
                collection=row.collection,
                note=row.note,
                created_at=row.created_at,
            )
            for row in rows
            if row.place_id in places  # taken-down places drop out
        ]
        next_cursor = None
        if more and rows:
            last = rows[-1]
            next_cursor = self._cursors.encode(
                {
                    "f": filters,
                    "t": last.created_at.isoformat(),
                    "p": str(last.place_id),
                    "k": last.collection,
                },
                scope=_SCOPE,
            )
        return SavedPlacePage(data=data, page=PageInfo(next_cursor=next_cursor))
