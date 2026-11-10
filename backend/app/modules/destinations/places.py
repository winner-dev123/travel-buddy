"""Places catalog (BL-4.01; DEST-003, LOC-009): reads, nearby and search, ingestion from licensed
sources, and the candidates AI itineraries are grounded on (AI-003).

* Only ``active`` places appear in nearby and search results. ``closed_permanently`` ones stay
  readable by ID (old posts and trips link them); ``hidden`` ones (taken down) answer 404.
* ``data_stale`` flags provider data older than :data:`STALE_AFTER` (DEST-003).
* Nearby uses the request's point only for this query, never stored (LOC-009). It is rounded to
  ~110 m like every other ``near`` input.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Float, and_, case, cast, delete, func, literal_column, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.ids import uuid7
from app.core.pagination import CursorCodec, Page, PageInfo
from app.core.time import Clock
from app.modules.destinations.domain import localized, parse_near
from app.modules.destinations.models import Destination as DestinationRow
from app.modules.destinations.models import Place as PlaceRow
from app.modules.destinations.models import PlaceLocalization
from app.modules.destinations.place_sources import SourceBatch
from app.modules.destinations.schemas import GeoPoint, Place, PlaceAttribution, PlaceSummary

STALE_AFTER = timedelta(days=180)
EARTH_RADIUS_M = 6_371_000.0
_LISTED = ("active",)
_READABLE = ("active", "closed_permanently")
_NEARBY_SCOPE = "places.nearby"
_SEARCH_LIMIT_MAX = 50


def _not_found() -> AppError:
    return AppError(ErrorCode.NOT_FOUND, "Place not found.")


def _invalid(field: str, message: str) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_FAILED,
        message,
        errors=[FieldError(field=field, code="invalid", message=message)],
    )


async def _names(
    session: AsyncSession, ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, dict[str, str]]:
    grouped: dict[uuid.UUID, dict[str, str]] = {i: {} for i in ids}
    if ids:
        rows = await session.scalars(
            select(PlaceLocalization).where(PlaceLocalization.place_id.in_(list(ids)))
        )
        for row in rows:
            grouped[row.place_id][row.locale] = row.name
    return grouped


def _summary(
    row: PlaceRow, names: Mapping[uuid.UUID, Mapping[str, str]], preferences: Sequence[str]
) -> PlaceSummary:
    return PlaceSummary(
        id=row.id,
        name=localized(dict(names.get(row.id, {})), preferences) or row.default_name,
        category=row.category,  # type: ignore[arg-type]
        destination_id=row.destination_id,
        location=GeoPoint(lat=row.lat, lng=row.lng),
    )


async def summaries(
    session: AsyncSession, rows: Sequence[PlaceRow], preferences: Sequence[str]
) -> list[PlaceSummary]:
    names = await _names(session, [row.id for row in rows])
    return [_summary(row, names, preferences) for row in rows]


async def place_summaries(
    session: AsyncSession, ids: Sequence[uuid.UUID], preferences: Sequence[str]
) -> dict[uuid.UUID, PlaceSummary]:
    """Readable places among ``ids`` (trips and AI proposals join them; hidden ones are omitted)."""
    if not ids:
        return {}
    rows = (
        await session.scalars(
            select(PlaceRow).where(PlaceRow.id.in_(list(ids)), PlaceRow.status.in_(_READABLE))
        )
    ).all()
    return {summary.id: summary for summary in await summaries(session, rows, preferences)}


async def is_listed(session: AsyncSession, place_id: uuid.UUID) -> bool:
    """Whether a place can be newly referenced (itinerary items, saved places)."""
    found = await session.scalar(
        select(PlaceRow.id).where(PlaceRow.id == place_id, PlaceRow.status.in_(_LISTED))
    )
    return found is not None


def _within(destination_id: uuid.UUID) -> Any:
    """Places in a destination or any of its descendants (``path`` holds every ancestor)."""
    return PlaceRow.destination_id.in_(
        select(DestinationRow.id).where(DestinationRow.path.contains([destination_id]))
    )


@dataclass(frozen=True, slots=True)
class PlaceCandidate:
    """A catalog place an AI itinerary may reference, with what the proposal joins."""

    summary: PlaceSummary
    provider: str
    license: str
    attribution_url: str | None
    data_freshness_at: datetime


async def place_candidates(
    session: AsyncSession,
    destination_id: uuid.UUID,
    preferences: Sequence[str],
    *,
    limit: int = 60,
    per_category: int = 12,
) -> list[PlaceCandidate]:
    """The most popular active places in the destination, at most ``per_category`` of each
    category so every kind of activity is represented (AI-003)."""
    ranked = (
        select(
            PlaceRow.id,
            func.row_number()
            .over(
                partition_by=PlaceRow.category,
                order_by=(PlaceRow.popularity_score.desc(), PlaceRow.default_name),
            )
            .label("rank"),
        )
        .where(_within(destination_id), PlaceRow.status.in_(_LISTED))
        .subquery()
    )
    rows = (
        await session.scalars(
            select(PlaceRow)
            .join(ranked, ranked.c.id == PlaceRow.id)
            .where(ranked.c.rank <= per_category)
            .order_by(PlaceRow.popularity_score.desc(), PlaceRow.default_name)
            .limit(limit)
        )
    ).all()
    found = await summaries(session, rows, preferences)
    return [
        PlaceCandidate(
            summary=summary,
            provider=row.provider,
            license=row.license,
            attribution_url=row.attribution_url,
            data_freshness_at=row.data_freshness_at,
        )
        for row, summary in zip(rows, found, strict=True)
    ]


# ─────────────────────────────── ingestion ───────────────────────────────


@dataclass(frozen=True, slots=True)
class IngestResult:
    created: int
    updated: int


async def ingest(
    session: AsyncSession, destination_id: uuid.UUID, batch: SourceBatch, *, now: datetime
) -> IngestResult:
    """Upsert a source batch by ``(provider, provider_place_id)``. New places join
    ``destination_id``; existing ones keep their (possibly more specific) destination and an
    editorial ``hidden`` status. Localized names are replaced."""
    created = updated = 0
    for place in batch.places:
        values: dict[str, Any] = {
            "category": place.category,
            "default_name": place.name,
            "lat": place.lat,
            "lng": place.lng,
            "address": dict(place.address) if place.address else None,
            "license": batch.license,
            "attribution_text": batch.attribution_text,
            "attribution_url": batch.attribution_url,
            "data_freshness_at": batch.retrieved_at,
            "attributes": dict(place.attributes),
            "popularity_score": place.popularity,
            "updated_at": now,
        }
        statement: Any = (
            insert(PlaceRow)
            .values(
                id=uuid7(),
                destination_id=destination_id,
                provider=batch.provider,
                provider_place_id=place.provider_place_id,
                status=place.status,
                **values,
            )
            .on_conflict_do_update(
                index_elements=[PlaceRow.provider, PlaceRow.provider_place_id],
                set_={
                    **values,
                    # An editorial takedown survives re-ingestion.
                    "status": text(
                        "CASE WHEN places.status = 'hidden' THEN 'hidden' ELSE excluded.status END"
                    ),
                },
            )
            .returning(PlaceRow.id, literal_column("(xmax = 0)").label("inserted"))
        )
        row = (await session.execute(statement)).one()
        if row.inserted:
            created += 1
        else:
            updated += 1
        await session.execute(delete(PlaceLocalization).where(PlaceLocalization.place_id == row.id))
        if place.names:
            session.add_all(
                PlaceLocalization(place_id=row.id, locale=locale, name=name)
                for locale, name in place.names.items()
            )
    await session.flush()
    return IngestResult(created=created, updated=updated)


# ─────────────────────────────── reads ───────────────────────────────


def _distance_m(lat: float, lng: float) -> Any:
    """Great-circle (haversine) distance from a point to each place, in metres (SQL)."""
    dlat = func.radians(PlaceRow.lat - lat)
    dlng = func.radians(PlaceRow.lng - lng)
    a = func.power(func.sin(dlat / 2), 2) + math.cos(math.radians(lat)) * func.cos(
        func.radians(PlaceRow.lat)
    ) * func.power(func.sin(dlng / 2), 2)
    return cast(2 * EARTH_RADIUS_M, Float) * func.asin(func.sqrt(func.least(a, 1.0)))


class PlaceService:
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

    async def get(self, place_id: uuid.UUID, *, preferences: Sequence[str]) -> Place:
        async with self._sessionmaker() as session:
            row = await session.get(PlaceRow, place_id)
            if row is None or row.status not in _READABLE:
                raise _not_found()
            [summary] = await summaries(session, [row], preferences)
        return Place(
            **summary.model_dump(),
            address=row.address,
            attributes=row.attributes,
            data_freshness_at=row.data_freshness_at,
            data_stale=self._clock.now() - row.data_freshness_at > STALE_AFTER,
            attribution=PlaceAttribution(
                provider=row.provider,
                license=row.license,
                text=row.attribution_text,
                url=row.attribution_url,
            ),
            status=row.status,  # type: ignore[arg-type]
        )

    async def search(
        self,
        q: str,
        *,
        destination_id: uuid.UUID,
        categories: Sequence[str],
        limit: int,
        preferences: Sequence[str],
    ) -> Page[PlaceSummary]:
        """Accent/case-insensitive, typo-tolerant name search within a destination (and its
        descendants), best match first."""
        term = func.f_unaccent(func.lower(q.strip()))
        names = (
            select(PlaceLocalization.place_id.label("place_id"), PlaceLocalization.name)
            .union_all(select(PlaceRow.id, PlaceRow.default_name))
            .subquery()
        )
        name = func.f_unaccent(func.lower(names.c.name))
        score = func.max(
            func.greatest(
                func.similarity(name, term),
                func.word_similarity(term, name),
                case((name.like(term + "%"), 1.0), else_=0.0),
            )
        )
        statement = (
            select(PlaceRow.id, score.label("score"))
            .join(names, names.c.place_id == PlaceRow.id)
            .where(
                _within(destination_id),
                PlaceRow.status.in_(_LISTED),
                or_(
                    name.op("%")(term),
                    term.op("<%")(name),
                    name.like(term + "%"),
                    name.like("%" + term + "%"),
                ),
                *([PlaceRow.category.in_(list(categories))] if categories else []),
            )
            .group_by(PlaceRow.id, PlaceRow.popularity_score, PlaceRow.default_name)
            .order_by(text("score DESC"), PlaceRow.popularity_score.desc(), PlaceRow.default_name)
            .limit(min(limit, _SEARCH_LIMIT_MAX))
        )
        async with self._sessionmaker() as session:
            ids = [row.id for row in await session.execute(statement)]
            found = await place_summaries(session, ids, preferences)
        return Page[PlaceSummary](
            data=[found[i] for i in ids if i in found], page=PageInfo(next_cursor=None)
        )

    async def nearby(
        self,
        near: str,
        *,
        radius_m: int,
        categories: Sequence[str],
        cursor: str | None,
        limit: int,
        preferences: Sequence[str],
    ) -> Page[PlaceSummary]:
        try:
            point = parse_near(near)
        except ValueError as exc:
            raise _invalid("/near", "Use near=lat,lng.") from exc
        lat, lng = point.lat, point.lng
        filters = {"n": f"{lat:.3f},{lng:.3f}", "r": radius_m, "c": sorted(categories)}
        offset = 0
        if cursor is not None:
            decoded = self._cursors.decode(cursor, scope=_NEARBY_SCOPE)
            if decoded.get("f") != filters:
                raise AppError(ErrorCode.INVALID_CURSOR, "The cursor belongs to another query.")
            offset = int(decoded.get("o", 0))
        dlat = radius_m / 111_320.0
        dlng = radius_m / max(111_320.0 * math.cos(math.radians(lat)), 1.0)
        distance = _distance_m(lat, lng)
        statement = (
            select(PlaceRow)
            .where(
                PlaceRow.status.in_(_LISTED),
                and_(PlaceRow.lat.between(lat - dlat, lat + dlat)),
                and_(PlaceRow.lng.between(lng - dlng, lng + dlng)),
                distance <= radius_m,
                *([PlaceRow.category.in_(list(categories))] if categories else []),
            )
            .order_by(distance, PlaceRow.id)
            .offset(offset)
            .limit(limit + 1)
        )
        async with self._sessionmaker() as session:
            rows = list((await session.scalars(statement)).all())
            more = len(rows) > limit
            data = await summaries(session, rows[:limit], preferences)
        next_cursor = (
            self._cursors.encode({"f": filters, "o": offset + limit}, scope=_NEARBY_SCOPE)
            if more
            else None
        )
        return Page[PlaceSummary](data=data, page=PageInfo(next_cursor=next_cursor))
