"""Public interface of the destinations module (DEST-001/002/004/006, LOC-002/005/006).

Only ``active`` destinations are visible. Names and taglines are localized per request from the
Accept-Language preferences with an English fallback.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, and_, exists, func, or_, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode
from app.core.pagination import CursorCodec, Page, PageInfo
from app.modules.destinations.domain import join_path, localized, parse_near
from app.modules.destinations.models import (
    Destination as DestinationRow,
)
from app.modules.destinations.models import (
    DestinationLocalization,
    DestinationStatus,
)

# The places catalog (BL-4.01) belongs to this module; other modules use it through here.
from app.modules.destinations.places import STALE_AFTER as PLACE_STALE_AFTER
from app.modules.destinations.places import (
    PlaceCandidate,
    PlaceService,
    place_candidates,
    place_summaries,
)
from app.modules.destinations.places import is_listed as place_is_listed
from app.modules.destinations.schemas import Destination, DestinationSummary, GeoPoint

_ACTIVE = DestinationRow.status == DestinationStatus.ACTIVE
_SEARCH_LIMIT_MAX = 20


@dataclass(frozen=True, slots=True)
class ListFilters:
    kinds: tuple[str, ...] = ()
    country: str | None = None
    continent: str | None = None
    featured: bool | None = None

    def as_payload(self) -> dict[str, Any]:
        return {
            "k": list(self.kinds),
            "c": self.country,
            "ct": self.continent,
            "f": self.featured,
        }


def _not_found() -> AppError:
    return AppError(ErrorCode.NOT_FOUND, "Destination not found.")


class DestinationService:
    def __init__(
        self, *, sessionmaker: async_sessionmaker[AsyncSession], cursors: CursorCodec
    ) -> None:
        self._sessionmaker = sessionmaker
        self._cursors = cursors

    # ─────────────────────────────── listings ───────────────────────────────

    async def list(
        self,
        filters: ListFilters,
        *,
        sort: str,
        cursor: str | None,
        limit: int,
        preferences: Sequence[str],
    ) -> Page[DestinationSummary]:
        """Directory/sitemap listing (DEST-006). ``sort=slug`` is stable for full enumeration."""
        query = select(DestinationRow).where(_ACTIVE)
        if filters.kinds:
            query = query.where(DestinationRow.kind.in_(filters.kinds))
        if filters.country:
            query = query.where(DestinationRow.country_code == filters.country)
        if filters.continent:
            query = query.where(DestinationRow.continent == filters.continent)
        if filters.featured is not None:
            query = query.where(DestinationRow.is_featured.is_(filters.featured))
        scope = f"destinations.list.{sort}"
        return await self._page(
            query, scope, filters.as_payload(), sort, cursor, limit, preferences
        )

    async def featured(
        self, *, cursor: str | None, limit: int, preferences: Sequence[str]
    ) -> Page[DestinationSummary]:
        query = select(DestinationRow).where(_ACTIVE, DestinationRow.is_featured.is_(True))
        return await self._page(
            query, "destinations.featured", {}, "popularity", cursor, limit, preferences
        )

    async def children(
        self,
        destination_id: uuid.UUID,
        *,
        cursor: str | None,
        limit: int,
        preferences: Sequence[str],
    ) -> Page[DestinationSummary]:
        async with self._sessionmaker() as session:
            if not await session.scalar(
                select(exists().where(DestinationRow.id == destination_id, _ACTIVE))
            ):
                raise _not_found()
        query = select(DestinationRow).where(_ACTIVE, DestinationRow.parent_id == destination_id)
        scope = f"destinations.children.{destination_id}"
        return await self._page(query, scope, {}, "popularity", cursor, limit, preferences)

    async def _page(
        self,
        query: Select[tuple[DestinationRow]],
        scope: str,
        filters: dict[str, Any],
        sort: str,
        cursor: str | None,
        limit: int,
        preferences: Sequence[str],
    ) -> Page[DestinationSummary]:
        if cursor:
            position = self._cursors.decode(cursor, scope=scope)
            if position.get("filters") != filters:
                raise AppError(ErrorCode.INVALID_CURSOR, "Cursor does not match these filters.")
            after_slug = str(position["slug"])
            if sort == "slug":
                query = query.where(DestinationRow.slug > after_slug)
            else:
                score = float(position["score"])
                query = query.where(
                    or_(
                        DestinationRow.popularity_score < score,
                        and_(
                            DestinationRow.popularity_score == score,
                            DestinationRow.slug > after_slug,
                        ),
                    )
                )
        if sort == "slug":
            query = query.order_by(DestinationRow.slug)
        else:
            query = query.order_by(DestinationRow.popularity_score.desc(), DestinationRow.slug)
        async with self._sessionmaker() as session:
            rows = list((await session.scalars(query.limit(limit + 1))).all())
            has_more = len(rows) > limit
            rows = rows[:limit]
            summaries = await _summaries(session, rows, preferences)
        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            next_cursor = self._cursors.encode(
                {"filters": filters, "slug": last.slug, "score": last.popularity_score},
                scope=scope,
            )
        return Page[DestinationSummary](
            data=summaries, page=PageInfo(next_cursor=next_cursor, has_more=has_more)
        )

    # ─────────────────────────────── search ───────────────────────────────

    async def search(
        self,
        q: str,
        *,
        kinds: Sequence[str],
        country: str | None,
        limit: int,
        preferences: Sequence[str],
    ) -> Page[DestinationSummary]:
        """Accent/case-insensitive, typo-tolerant search over every localized and alternative
        name (DEST-001), best match first."""
        statement = text(
            """
            WITH q AS (SELECT f_unaccent(lower(:q)) AS term),
            names AS (
                SELECT l.destination_id, f_unaccent(lower(l.name)) AS name
                  FROM destination_localizations AS l
                UNION ALL
                SELECT l.destination_id, f_unaccent(lower(alt)) AS name
                  FROM destination_localizations AS l, unnest(l.alt_names) AS alt
                UNION ALL
                SELECT d.id, f_unaccent(lower(d.default_name)) FROM destinations AS d
            )
            SELECT d.id,
                   max(greatest(similarity(n.name, q.term), word_similarity(q.term, n.name),
                                CASE WHEN n.name LIKE q.term || '%' THEN 1.0 ELSE 0 END)) AS score
              FROM q, names AS n
              JOIN destinations AS d ON d.id = n.destination_id
             WHERE d.status = 'active'
               AND (cardinality(CAST(:kinds AS text[])) = 0 OR d.kind = ANY(CAST(:kinds AS text[])))
               AND (CAST(:country AS text) IS NULL OR d.country_code = CAST(:country AS text))
               AND (n.name % q.term OR q.term <% n.name OR n.name LIKE q.term || '%')
             GROUP BY d.id, d.popularity_score, d.slug
             ORDER BY score DESC, d.popularity_score DESC, d.slug
             LIMIT :limit
            """
        )
        async with self._sessionmaker() as session:
            result = await session.execute(
                statement,
                {
                    "q": q.strip(),
                    "kinds": list(kinds),
                    "country": country,
                    "limit": min(limit, _SEARCH_LIMIT_MAX),
                },
            )
            ids = [row.id for row in result]
            rows_by_id = {
                row.id: row
                for row in (
                    await session.scalars(select(DestinationRow).where(DestinationRow.id.in_(ids)))
                ).all()
            }
            ordered = [rows_by_id[i] for i in ids if i in rows_by_id]
            summaries = await _summaries(session, ordered, preferences)
        return Page[DestinationSummary](data=summaries, page=PageInfo(next_cursor=None))

    # ─────────────────────────────── single destination ───────────────────────────────

    async def get(self, destination_id: uuid.UUID, *, preferences: Sequence[str]) -> Destination:
        async with self._sessionmaker() as session:
            row = await session.scalar(
                select(DestinationRow).where(DestinationRow.id == destination_id, _ACTIVE)
            )
            if row is None:
                raise _not_found()
            return await _detail(session, row, preferences)

    async def lookup(self, path: str, *, preferences: Sequence[str]) -> Destination:
        """``brazil/rio-de-janeiro`` -> destination, matching one level at a time."""
        segments = [s for s in path.strip("/").split("/") if s]
        if not segments:
            raise _not_found()
        async with self._sessionmaker() as session:
            parent_id: uuid.UUID | None = None
            row: DestinationRow | None = None
            for segment in segments:
                parent_filter = (
                    DestinationRow.parent_id.is_(None)
                    if parent_id is None
                    else DestinationRow.parent_id == parent_id
                )
                row = await session.scalar(
                    select(DestinationRow).where(
                        _ACTIVE, parent_filter, DestinationRow.path_segment == segment
                    )
                )
                if row is None:
                    raise _not_found()
                parent_id = row.id
            assert row is not None
            return await _detail(session, row, preferences)

    async def resolve(self, near: str, *, preferences: Sequence[str]) -> Destination:
        """Most specific destination covering a device point (LOC-005). The point is rounded to
        ~110 m, used for one lookup, and never stored or logged."""
        try:
            point = parse_near(near)
        except ValueError as exc:
            raise AppError(ErrorCode.VALIDATION_FAILED, "near must be 'lat,lng'.") from exc
        statement = text(
            """
            SELECT d.id
              FROM destination_boundaries AS b
              JOIN destinations AS d ON d.id = b.destination_id
             WHERE d.status = 'active'
               AND ST_Covers(b.boundary,
                             CAST(ST_SetSRID(ST_MakePoint(:lng, :lat), 4326) AS geography))
             ORDER BY d.depth DESC
             LIMIT 1
            """
        )
        async with self._sessionmaker() as session:
            try:
                found = await session.scalar(statement, {"lat": point.lat, "lng": point.lng})
            except DBAPIError as exc:  # no PostGIS / no boundaries table in this database
                raise AppError(
                    ErrorCode.SERVICE_UNAVAILABLE, "Location resolution is unavailable."
                ) from exc
            if found is None:
                raise AppError(
                    ErrorCode.LOCATION_UNRESOLVABLE,
                    "This location is outside the destinations we cover yet.",
                )
            row = await session.get(DestinationRow, found)
            assert row is not None
            return await _detail(session, row, preferences)


# ─────────────────────────────── assembly ───────────────────────────────


async def _localizations(
    session: AsyncSession, ids: set[uuid.UUID]
) -> dict[uuid.UUID, list[DestinationLocalization]]:
    grouped: dict[uuid.UUID, list[DestinationLocalization]] = {i: [] for i in ids}
    if ids:
        for loc in (
            await session.scalars(
                select(DestinationLocalization).where(
                    DestinationLocalization.destination_id.in_(ids)
                )
            )
        ).all():
            grouped[loc.destination_id].append(loc)
    return grouped


async def _summaries(
    session: AsyncSession, rows: Sequence[DestinationRow], preferences: Sequence[str]
) -> list[DestinationSummary]:
    ancestor_ids = {a for row in rows for a in row.path} - {row.id for row in rows}
    ancestors = {row.id: row for row in rows}
    if ancestor_ids:
        for row in (
            await session.scalars(select(DestinationRow).where(DestinationRow.id.in_(ancestor_ids)))
        ).all():
            ancestors[row.id] = row
    locs = await _localizations(session, set(ancestors))
    return [_summary(row, ancestors, locs, preferences) for row in rows]


def _name(
    row: DestinationRow,
    locs: dict[uuid.UUID, list[DestinationLocalization]],
    preferences: Sequence[str],
) -> str:
    texts = {loc.locale: loc.name for loc in locs.get(row.id, [])}
    return localized(texts, preferences) or row.default_name


def _summary(
    row: DestinationRow,
    known: dict[uuid.UUID, DestinationRow],
    locs: dict[uuid.UUID, list[DestinationLocalization]],
    preferences: Sequence[str],
) -> DestinationSummary:
    chain = [known[i] for i in row.path if i in known]
    country = next((d for d in chain if d.kind == "country"), None)
    taglines = {loc.locale: loc.tagline for loc in locs.get(row.id, []) if loc.tagline}
    return DestinationSummary.model_validate(
        {
            "id": row.id,
            "kind": row.kind,
            "slug": row.slug,
            "path": join_path([d.path_segment for d in chain]),
            "name": _name(row, locs, preferences),
            "country_code": row.country_code,
            "country_name": (
                _name(country, locs, preferences)
                if country is not None and country.id != row.id
                else None
            ),
            "continent": row.continent,
            "tagline": localized(taglines, preferences),
        }
    )


async def _detail(
    session: AsyncSession, row: DestinationRow, preferences: Sequence[str]
) -> Destination:
    chain_rows = (
        await session.scalars(select(DestinationRow).where(DestinationRow.id.in_(row.path)))
    ).all()
    known = {r.id: r for r in chain_rows} | {row.id: row}
    locs = await _localizations(session, set(known))
    ancestors = [
        _summary(known[i], known, locs, preferences) for i in row.path if i != row.id and i in known
    ]
    has_children = bool(
        await session.scalar(select(exists().where(DestinationRow.parent_id == row.id, _ACTIVE)))
    )
    base = _summary(row, known, locs, preferences).model_dump()
    return Destination.model_validate(
        {
            **base,
            "parent_id": row.parent_id,
            "ancestors": [a.model_dump() for a in ancestors],
            "centroid": GeoPoint(lat=row.centroid_lat, lng=row.centroid_lng).model_dump(),
            "time_zone": row.time_zone,
            "is_featured": row.is_featured,
            "has_children": has_children,
            "has_guides": row.has_guides,
        }
    )


# ─────────────────────────────── for other modules ───────────────────────────────


async def is_active(session: AsyncSession, destination_id: uuid.UUID) -> bool:
    return bool(
        await session.scalar(select(exists().where(DestinationRow.id == destination_id, _ACTIVE)))
    )


async def summaries_by_id(
    session: AsyncSession, ids: Sequence[uuid.UUID], preferences: Sequence[str]
) -> dict[uuid.UUID, DestinationSummary]:
    """Localized summaries of the ACTIVE destinations among ``ids`` (hidden ones are omitted)."""
    if not ids:
        return {}
    rows = (
        await session.scalars(select(DestinationRow).where(DestinationRow.id.in_(ids), _ACTIVE))
    ).all()
    return {summary.id: summary for summary in await _summaries(session, rows, preferences)}


async def planning_destination(
    session: AsyncSession, destination_id: uuid.UUID, preferences: Sequence[str]
) -> tuple[DestinationSummary, str] | None:
    """Localized summary and IANA time zone of an ACTIVE destination (AI trip context)."""
    row = await session.scalar(
        select(DestinationRow).where(DestinationRow.id == destination_id, _ACTIVE)
    )
    if row is None:
        return None
    [summary] = await _summaries(session, [row], preferences)
    return summary, row.time_zone


async def ancestry(session: AsyncSession, destination_id: uuid.UUID) -> list[uuid.UUID] | None:
    """IDs root -> self of an ACTIVE destination (post fan-out, LOC-006), or None."""
    path = await session.scalar(
        select(DestinationRow.path).where(DestinationRow.id == destination_id, _ACTIVE)
    )
    return list(path) if path is not None else None


async def id_for_path(session: AsyncSession, path: str) -> uuid.UUID | None:
    """An active destination by its slug path (``portugal/lisbon``), one level at a time."""
    parent_id: uuid.UUID | None = None
    for segment in (s for s in path.strip("/").split("/") if s):
        parent_filter = (
            DestinationRow.parent_id.is_(None)
            if parent_id is None
            else DestinationRow.parent_id == parent_id
        )
        parent_id = await session.scalar(
            select(DestinationRow.id).where(
                _ACTIVE, parent_filter, DestinationRow.path_segment == segment
            )
        )
        if parent_id is None:
            return None
    return parent_id


async def country_destination_id(session: AsyncSession, country_code: str) -> uuid.UUID | None:
    found: uuid.UUID | None = await session.scalar(
        select(DestinationRow.id).where(
            DestinationRow.kind == "country", DestinationRow.country_code == country_code, _ACTIVE
        )
    )
    return found


async def resolve_point(session: AsyncSession, lat: float, lng: float) -> uuid.UUID | None:
    """Most specific active destination covering a point, or None (also without PostGIS).
    The point must already be coarsened by the caller (LOC-003)."""
    statement = text(
        """
        SELECT d.id
          FROM destination_boundaries AS b
          JOIN destinations AS d ON d.id = b.destination_id
         WHERE d.status = 'active'
           AND ST_Covers(b.boundary,
                         CAST(ST_SetSRID(ST_MakePoint(:lng, :lat), 4326) AS geography))
         ORDER BY d.depth DESC LIMIT 1
        """
    )
    try:
        async with session.begin_nested():
            found: uuid.UUID | None = await session.scalar(statement, {"lat": lat, "lng": lng})
            return found
    except DBAPIError:
        return None


async def city_of(session: AsyncSession, destination_id: uuid.UUID) -> uuid.UUID:
    """The city-level ancestor (or self) used as the "Nearby" area; else the destination."""
    rows = (
        await session.execute(
            select(DestinationRow.id, DestinationRow.kind, DestinationRow.depth).where(
                DestinationRow.id.in_(
                    select(func.unnest(DestinationRow.path)).where(
                        DestinationRow.id == destination_id
                    )
                )
            )
        )
    ).all()
    cities = sorted((r for r in rows if r.kind == "city"), key=lambda r: r.depth, reverse=True)
    return cities[0].id if cities else destination_id


async def centroids(
    session: AsyncSession, ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[float, float]]:
    if not ids:
        return {}
    rows = await session.execute(
        select(DestinationRow.id, DestinationRow.centroid_lat, DestinationRow.centroid_lng).where(
            DestinationRow.id.in_(list(ids))
        )
    )
    return {row.id: (row.centroid_lat, row.centroid_lng) for row in rows}


def coarse_point(near: str) -> tuple[float, float]:
    """``lat,lng`` -> point rounded to ~110 m (LOC-003). Raises ``ValueError`` when malformed."""
    point = parse_near(near)
    return point.lat, point.lng


async def kind_of(session: AsyncSession, destination_id: uuid.UUID) -> str | None:
    """The kind (``city``, ``neighborhood``, …) of an active destination, or ``None``."""
    kind: str | None = await session.scalar(
        select(DestinationRow.kind).where(DestinationRow.id == destination_id, _ACTIVE)
    )
    return kind


__all__ = [
    "PLACE_STALE_AFTER",
    "DestinationService",
    "ListFilters",
    "PlaceCandidate",
    "PlaceService",
    "place_candidates",
    "place_is_listed",
    "place_summaries",
]
