"""Public interface of the destinations module (DEST-001/002/004/006, LOC-002/005/006).

Only ``active`` destinations are visible. Names and taglines are localized per request from the
Accept-Language preferences with an English fallback.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, exists, func, or_, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.pagination import CursorCodec, Page, PageInfo
from app.modules.destinations.domain import (
    StaleLocationError,
    check_fix_age,
    join_path,
    localized,
    parse_near,
)
from app.modules.destinations.domain import city_level_only as city_level_only
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
from app.modules.destinations.places import ids_within as place_ids_within
from app.modules.destinations.places import is_listed as place_is_listed
from app.modules.destinations.places import listed_destination as place_destination
from app.modules.destinations.places import search_ids as place_search_ids
from app.modules.destinations.schemas import (
    Destination,
    DestinationSummary,
    GeoPoint,
    Suggestion,
)
from app.modules.destinations.world_catalog import belonging
from app.modules.media import service as media
from app.modules.media.schemas import MediaRef
from app.modules.platform import service as platform

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


# Search as you type offers places to go, not administrative areas or addresses (ADR-0035).
SUGGEST_KINDS: tuple[str, ...] = ("country", "city", "district", "neighborhood", "area")
SUGGEST_PLACE_CATEGORIES: tuple[str, ...] = (
    "attraction",
    "museum",
    "beach",
    "viewpoint",
    "park",
    "trail",
    "market",
)


def destination_prominence(popularity_score: float) -> float:
    """0.05 to 0.35 added to a text match: towns come before places named alike, and launch
    cities (150) before their namesakes."""
    return 0.05 + min(1.0, max(0.0, popularity_score) / 150.0) * 0.3


def place_prominence(popularity: float) -> float:
    """Up to 0.2 added to a text match, from Wikipedia/Wikivoyage sitelinks (log scale)."""
    return min(1.0, math.log10(1.0 + max(0.0, popularity)) / math.log10(201.0)) * 0.2


def like_escape(term: str) -> str:
    """Literal ``%``, ``_`` and backslashes for LIKE (PostgreSQL's default escape character)."""
    return term.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")


async def normalized_term(session: AsyncSession, q: str) -> str:
    """The query as the indexes see names: unaccented and lower-case (``f_unaccent``)."""
    term: str | None = await session.scalar(select(func.f_unaccent(func.lower(q.strip()))))
    return term or ""


_SEARCH_SQL = text(
    """
    WITH hits AS (
        SELECT l.destination_id AS id, f_unaccent(lower(l.name)) AS name
          FROM destination_localizations AS l
         WHERE f_unaccent(lower(l.name)) % :term
            OR :term <% f_unaccent(lower(l.name))
            OR f_unaccent(lower(l.name)) LIKE :prefix
        UNION ALL
        SELECT d.id, f_unaccent(lower(d.default_name))
          FROM destinations AS d
         WHERE f_unaccent(lower(d.default_name)) % :term
            OR :term <% f_unaccent(lower(d.default_name))
            OR f_unaccent(lower(d.default_name)) LIKE :prefix
        UNION ALL
        SELECT l.destination_id, f_unaccent(lower(alt))
          FROM destination_localizations AS l, unnest(l.alt_names) AS alt
         WHERE :term <% f_search_names(l.alt_names)
            OR f_search_names(l.alt_names) LIKE :contains
    )
    SELECT d.id,
           max(greatest(similarity(h.name, :term), 0.9 * word_similarity(:term, h.name),
                        CASE WHEN h.name LIKE :prefix THEN 1.0 ELSE 0 END)) AS score
      FROM hits AS h
      JOIN destinations AS d ON d.id = h.id
     WHERE d.status = 'active'
       AND (cardinality(CAST(:kinds AS text[])) = 0 OR d.kind = ANY(CAST(:kinds AS text[])))
       AND (CAST(:country AS text) IS NULL OR d.country_code = CAST(:country AS text))
       AND (h.name % :term OR :term <% h.name OR h.name LIKE :prefix)
     GROUP BY d.id, d.popularity_score, d.slug
     ORDER BY score DESC, d.popularity_score DESC, d.slug
     LIMIT :limit
    """
)
# One or two letters: trigram similarity means nothing yet, so names that start with them.
_PREFIX_SQL = text(
    """
    WITH hits AS (
        SELECT l.destination_id AS id
          FROM destination_localizations AS l
         WHERE f_unaccent(lower(l.name)) LIKE :prefix
        UNION ALL
        SELECT d.id FROM destinations AS d WHERE f_unaccent(lower(d.default_name)) LIKE :prefix
        UNION ALL
        SELECT l.destination_id
          FROM destination_localizations AS l, unnest(l.alt_names) AS alt
         WHERE f_search_names(l.alt_names) LIKE :contains AND f_unaccent(lower(alt)) LIKE :prefix
    )
    SELECT DISTINCT d.id, 1.0 AS score, d.popularity_score, d.slug
      FROM hits AS h
      JOIN destinations AS d ON d.id = h.id
     WHERE d.status = 'active'
       AND (cardinality(CAST(:kinds AS text[])) = 0 OR d.kind = ANY(CAST(:kinds AS text[])))
       AND (CAST(:country AS text) IS NULL OR d.country_code = CAST(:country AS text))
     ORDER BY d.popularity_score DESC, d.slug
     LIMIT :limit
    """
)
SHORT_TERM = 3


async def _search_ids(
    session: AsyncSession,
    q: str,
    *,
    kinds: Sequence[str],
    country: str | None,
    limit: int,
) -> list[tuple[uuid.UUID, float]]:
    """(destination id, text score 0..1), best first. Every branch is backed by a trigram index
    (names, default names, alternative names), so search stays fast with the gazetteer."""
    term = await normalized_term(session, q)
    if not term:
        return []
    escaped = like_escape(term)
    result = await session.execute(
        _PREFIX_SQL if len(term) < SHORT_TERM else _SEARCH_SQL,
        {
            "term": term,
            "prefix": f"{escaped}%",
            "contains": f"%{escaped}%",
            "kinds": list(kinds),
            "country": country,
            "limit": limit,
        },
    )
    return [(row.id, float(row.score)) for row in result]


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
        """Directory/sitemap listing (DEST-006). ``sort=slug`` is stable for full enumeration.
        Gazetteer towns are left out until an editor lists them (ADR-0035)."""
        query = select(DestinationRow).where(_ACTIVE, DestinationRow.in_directory.is_(True))
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
        query = select(DestinationRow).where(
            _ACTIVE,
            DestinationRow.parent_id == destination_id,
            DestinationRow.in_directory.is_(True),
        )
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
        name (DEST-001), best match first (then the most popular)."""
        async with self._sessionmaker() as session:
            ranked = await _search_ids(
                session, q, kinds=kinds, country=country, limit=min(limit, _SEARCH_LIMIT_MAX)
            )
            summaries = await self._summaries_by_id(session, [i for i, _ in ranked], preferences)
        return Page[DestinationSummary](
            data=[summaries[i] for i, _ in ranked if i in summaries],
            page=PageInfo(next_cursor=None),
        )

    async def suggest(self, q: str, *, limit: int, preferences: Sequence[str]) -> Page[Suggestion]:
        """Search as you type (ADR-0035): towns, neighbourhoods and countries together with the
        tourist places in them, never streets or addresses. Text match first, then how well
        known the place is."""
        async with self._sessionmaker() as session:
            destinations = await _search_ids(
                session, q, kinds=SUGGEST_KINDS, country=None, limit=limit
            )
            places = await place_search_ids(
                session, q, categories=SUGGEST_PLACE_CATEGORIES, limit=limit
            )
            rows = {
                row.id: row
                for row in (
                    await session.scalars(
                        select(DestinationRow).where(
                            DestinationRow.id.in_([i for i, _ in destinations])
                        )
                    )
                ).all()
            }
            found = await place_summaries(session, [i for i, _, _ in places], preferences)
            ranked: list[tuple[float, str, uuid.UUID]] = []
            for destination_id, score in destinations:
                row = rows.get(destination_id)
                if row is not None:
                    ranked.append(
                        (score + destination_prominence(row.popularity_score), "d", row.id)
                    )
            for place_id, score, popularity in places:
                if place_id in found:
                    ranked.append((score + place_prominence(popularity), "p", place_id))
            ranked.sort(key=lambda item: -item[0])
            ranked = ranked[:limit]
            wanted = {i for _, kind, i in ranked if kind == "d"}
            wanted |= {found[i].destination_id for _, kind, i in ranked if kind == "p"}
            summaries = await self._summaries_by_id(session, list(wanted), preferences)
        suggestions: list[Suggestion] = []
        for _, kind, item_id in ranked:
            if kind == "d" and item_id in summaries:
                suggestions.append(Suggestion(type="destination", destination=summaries[item_id]))
            elif kind == "p" and found[item_id].destination_id in summaries:
                place = found[item_id]
                suggestions.append(
                    Suggestion(
                        type="place", destination=summaries[place.destination_id], place=place
                    )
                )
        return Page[Suggestion](data=suggestions, page=PageInfo(next_cursor=None))

    async def _summaries_by_id(
        self, session: AsyncSession, ids: Sequence[uuid.UUID], preferences: Sequence[str]
    ) -> dict[uuid.UUID, DestinationSummary]:
        if not ids:
            return {}
        rows = (
            await session.scalars(
                select(DestinationRow).where(DestinationRow.id.in_(list(ids)), _ACTIVE)
            )
        ).all()
        return {summary.id: summary for summary in await _summaries(session, rows, preferences)}

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

    async def resolve(
        self, near: str, *, preferences: Sequence[str], city_level: bool = False
    ) -> Destination:
        """The destination a device point is in (LOC-005), or only its town when the reading is
        coarse (LOC-008). The point is rounded to ~110 m, used for one lookup, and never stored
        or logged.

        See ``resolve_point``; works without PostGIS (towns only)."""
        try:
            point = parse_near(near)
        except ValueError as exc:
            raise AppError(ErrorCode.VALIDATION_FAILED, "near must be 'lat,lng'.") from exc
        async with self._sessionmaker() as session:
            found = await resolve_point(session, point.lat, point.lng)
            if found is None:
                raise AppError(
                    ErrorCode.LOCATION_UNRESOLVABLE,
                    "This location is outside the destinations we cover yet.",
                )
            if city_level:
                found = await city_of(session, found)
            row = await session.get(DestinationRow, found)
            assert row is not None
            return await _detail(session, row, preferences)


# ─────────────────────────────── point -> destination ───────────────────────────────

# Farther than this from every town, a point resolves only through a polygon (or not at all).
MAX_TOWN_KM = 80.0
_KM_PER_DEGREE = 111.32
_APPROXIMATE_SOURCE = "approximate-bbox"


@dataclass(frozen=True, slots=True)
class Covering:
    id: uuid.UUID
    kind: str
    source: str
    distance_km: float
    reach_km: float


@dataclass(frozen=True, slots=True)
class NearestTown:
    id: uuid.UUID
    distance_km: float
    reach_km: float

    @property
    def belonging(self) -> float:
        return belonging(self.distance_km, self.reach_km)


def _choose(covering: Covering | None, town: NearestTown | None) -> uuid.UUID | None:
    if covering is not None and covering.kind not in {"country", "admin_region", "city"}:
        return covering.id  # a neighbourhood or district polygon is the most specific answer
    if covering is not None and covering.kind == "city":
        if covering.source != _APPROXIMATE_SOURCE or town is None or town.id == covering.id:
            return covering.id
        # An approximate box spills over neighbours: the closer town (by size) wins.
        own = belonging(covering.distance_km, covering.reach_km)
        return town.id if town.belonging < own else covering.id
    if town is not None:
        return town.id
    return covering.id if covering is not None else None


# Great-circle distance (km) from the point, and the town's reach (as ``town_reach_km``).
_COVERING_SQL = text(
    """
    SELECT d.id, d.kind, b.source,
           6371.0 * 2 * asin(sqrt(least(1.0,
                     power(sin(radians(d.centroid_lat - :lat) / 2), 2)
                     + cos(radians(:lat)) * cos(radians(d.centroid_lat))
                       * power(sin(radians(d.centroid_lng - :lng) / 2), 2)))) AS distance_km,
           least(15.0,
                 0.5 * sqrt(greatest(coalesce(d.population, 0), 0) / (pi() * 5000.0)))
             AS reach_km
      FROM destination_boundaries AS b
      JOIN destinations AS d ON d.id = b.destination_id
     WHERE d.status = 'active'
       AND ST_Covers(b.boundary, CAST(ST_SetSRID(ST_MakePoint(:lng, :lat), 4326) AS geography))
     ORDER BY d.depth DESC
     LIMIT 1
    """
)
_NEAREST_TOWN_SQL = text(
    """
    SELECT id, distance_km, reach_km FROM (
        SELECT d.id,
               6371.0 * 2 * asin(sqrt(least(1.0,
                     power(sin(radians(d.centroid_lat - :lat) / 2), 2)
                     + cos(radians(:lat)) * cos(radians(d.centroid_lat))
                       * power(sin(radians(d.centroid_lng - :lng) / 2), 2)))) AS distance_km,
               least(15.0,
                 0.5 * sqrt(greatest(coalesce(d.population, 0), 0) / (pi() * 5000.0)))
             AS reach_km
          FROM destinations AS d
         WHERE d.kind = 'city' AND d.status = 'active'
           AND d.centroid_lat BETWEEN :lat - :dlat AND :lat + :dlat
           AND d.centroid_lng BETWEEN :lng - :dlng AND :lng + :dlng
    ) AS t
     WHERE distance_km <= :max_km
     ORDER BY distance_km / (reach_km + 1.0), distance_km
     LIMIT 1
    """
)
_NEAREST_UNBOUNDED_TOWN_SQL = text(
    """
    SELECT id, distance_km, reach_km FROM (
        SELECT d.id,
               6371.0 * 2 * asin(sqrt(least(1.0,
                     power(sin(radians(d.centroid_lat - :lat) / 2), 2)
                     + cos(radians(:lat)) * cos(radians(d.centroid_lat))
                       * power(sin(radians(d.centroid_lng - :lng) / 2), 2)))) AS distance_km,
               least(15.0,
                 0.5 * sqrt(greatest(coalesce(d.population, 0), 0) / (pi() * 5000.0)))
             AS reach_km
          FROM destinations AS d
         WHERE d.kind = 'city' AND d.status = 'active'
           AND d.centroid_lat BETWEEN :lat - :dlat AND :lat + :dlat
           AND d.centroid_lng BETWEEN :lng - :dlng AND :lng + :dlng
           AND NOT EXISTS (SELECT 1 FROM destination_boundaries AS b
                            WHERE b.destination_id = d.id AND b.source <> 'approximate-bbox')
    ) AS t
     WHERE distance_km <= :max_km
     ORDER BY distance_km / (reach_km + 1.0), distance_km
     LIMIT 1
    """
)


async def _boundaries_available(session: AsyncSession) -> bool:
    return bool(
        await session.scalar(text("SELECT to_regclass('destination_boundaries') IS NOT NULL"))
    )


async def _covering_destination(session: AsyncSession, lat: float, lng: float) -> Covering | None:
    """The most specific destination whose boundary covers the point (PostGIS only)."""
    try:
        async with session.begin_nested():  # a failure must not abort the caller's transaction
            row = (await session.execute(_COVERING_SQL, {"lat": lat, "lng": lng})).first()
    except DBAPIError:  # PostGIS functions missing in this database
        return None
    if row is None:
        return None
    return Covering(row.id, row.kind, row.source, float(row.distance_km), float(row.reach_km))


async def nearest_town(
    session: AsyncSession,
    lat: float,
    lng: float,
    *,
    max_km: float = MAX_TOWN_KM,
    licensed_polygons: bool = False,
) -> NearestTown | None:
    """The town a point belongs to (``world_catalog.belonging``) within ``max_km``, using the
    centroid index (a box first, then great-circle distance). With ``licensed_polygons``, towns
    with real city limits are left out: the point was not inside them."""
    dlat = max_km / _KM_PER_DEGREE
    dlng = min(180.0, max_km / (_KM_PER_DEGREE * max(0.01, math.cos(math.radians(lat)))))
    row = (
        await session.execute(
            _NEAREST_UNBOUNDED_TOWN_SQL if licensed_polygons else _NEAREST_TOWN_SQL,
            {"lat": lat, "lng": lng, "dlat": dlat, "dlng": dlng, "max_km": max_km},
        )
    ).first()
    if row is None:
        return None
    return NearestTown(row.id, float(row.distance_km), float(row.reach_km))


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
    covers = await _covers(session, rows)
    return [_summary(row, ancestors, locs, preferences, covers) for row in rows]


async def _covers(
    session: AsyncSession, rows: Sequence[DestinationRow]
) -> dict[uuid.UUID, MediaRef]:
    """Covers by media id; an asset whose rights were revoked is simply absent (DEST-007)."""
    return await media.editorial_refs(
        session, [row.cover_media_id for row in rows if row.cover_media_id is not None]
    )


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
    covers: dict[uuid.UUID, MediaRef] | None = None,
) -> DestinationSummary:
    chain = [known[i] for i in row.path if i in known]
    country = next((d for d in chain if d.kind == "country"), None)
    city = next((d for d in reversed(chain[:-1]) if d.kind == "city"), None)
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
            # Below the country: a town's region, or the city a neighbourhood belongs to.
            "region_name": row.region_name or (_name(city, locs, preferences) if city else None),
            "continent": row.continent,
            "tagline": localized(taglines, preferences),
            "cover": (covers or {}).get(row.cover_media_id) if row.cover_media_id else None,
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
    covers = await _covers(session, list(known.values()))
    ancestors = [
        _summary(known[i], known, locs, preferences, covers)
        for i in row.path
        if i != row.id and i in known
    ]
    has_children = bool(
        await session.scalar(select(exists().where(DestinationRow.parent_id == row.id, _ACTIVE)))
    )
    base = _summary(row, known, locs, preferences, covers).model_dump()
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
    """The destination a point is in (LOC-005), or None far from every town (also without
    PostGIS). The point must already be coarsened by the caller (LOC-003).

    A licensed polygon (neighbourhood or city limits) wins. Otherwise the point belongs to the
    nearest town weighed by size (``world_catalog.belonging``) within ``MAX_TOWN_KM``; an
    approximate bounding box decides only when no town is closer (ADR-0035)."""
    polygons = await _boundaries_available(session)
    covering = await _covering_destination(session, lat, lng) if polygons else None
    town = await nearest_town(session, lat, lng, licensed_polygons=polygons)
    return _choose(covering, town)


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


def ensure_fresh_fix(captured_at: datetime | None, now: datetime, *, field: str) -> None:
    """Refuse a device location older than 15 minutes (``stale_location``, LOC-007) or one
    timestamped in the future; a missing timestamp is accepted."""
    try:
        check_fix_age(captured_at, now)
    except StaleLocationError as exc:
        message = "Your location is out of date. Locate again."
        raise AppError(
            ErrorCode.STALE_LOCATION,
            message,
            errors=[FieldError(field=field, code="stale_location", message=message)],
        ) from exc
    except ValueError as exc:
        message = "The location time is in the future."
        raise AppError(
            ErrorCode.VALIDATION_FAILED,
            message,
            errors=[FieldError(field=field, code="invalid", message=message)],
        ) from exc


def coarse_point(near: str) -> tuple[float, float]:
    """``lat,lng`` -> point rounded to ~110 m (LOC-003). Raises ``ValueError`` when malformed."""
    point = parse_near(near)
    return point.lat, point.lng


async def set_has_guides(session: AsyncSession, destination_id: uuid.UUID, value: bool) -> None:
    """Maintained by the guides module when it publishes or retires guides (DEST-006)."""
    await session.execute(
        update(DestinationRow).where(DestinationRow.id == destination_id).values(has_guides=value)
    )


async def detail_by_id(
    session: AsyncSession, destination_id: uuid.UUID, preferences: Sequence[str]
) -> Destination | None:
    """An active destination with its ancestors and public centroid, or ``None``."""
    row = await session.scalar(
        select(DestinationRow).where(DestinationRow.id == destination_id, _ACTIVE)
    )
    return None if row is None else await _detail(session, row, preferences)


async def kind_of(session: AsyncSession, destination_id: uuid.UUID) -> str | None:
    """The kind (``city``, ``neighborhood``, …) of an active destination, or ``None``."""
    kind: str | None = await session.scalar(
        select(DestinationRow.kind).where(DestinationRow.id == destination_id, _ACTIVE)
    )
    return kind


_COVER_PROBLEMS = {
    "not_editorial": "Covers must be editorial media uploaded by content staff.",
    "not_ready": "The cover is still processing or was rejected.",
    "rights_not_verified": "Verify the rights of this image before publishing it.",
}


async def cover_rights_changed(session: AsyncSession, media_id: uuid.UUID) -> int:
    """Purge cached pages of destinations using this cover after its rights changed (a revoked
    cover disappears at once, not when the cache expires). Returns how many were affected."""
    rows = (
        await session.scalars(
            select(DestinationRow).where(DestinationRow.cover_media_id == media_id)
        )
    ).all()
    for row in rows:
        platform.record_event(
            session,
            aggregate_type="destination",
            aggregate_id=row.id,
            event_type="destination.updated",
            payload={
                "destination_id": str(row.id),
                "slug": row.slug,
                "changed": ["cover"],
                "status": row.status,
                "is_featured": row.is_featured,
            },
        )
    return len(rows)


async def admin_update(
    session: AsyncSession,
    destination_id: uuid.UUID,
    *,
    is_featured: bool | None,
    status: str | None,
    cover_media_id: uuid.UUID | None = None,
    set_cover: bool = False,
) -> Destination:
    """Featured flag, visibility and cover, set by content staff (DEST-004, DEST-007); the admin
    module audits it in the same transaction. Hidden destinations drop out of every public read;
    the ``destination.updated`` event purges the cached web pages at once (SAFE-012). A cover
    must be editorial media that is processed and whose rights were verified."""
    row = await session.get(DestinationRow, destination_id, with_for_update=True)
    if row is None:
        raise _not_found()
    changed: list[str] = []
    if set_cover and row.cover_media_id != cover_media_id:
        if cover_media_id is not None:
            problem = await media.editorial_problem(session, cover_media_id)
            if problem is not None:
                message = _COVER_PROBLEMS[problem]
                raise AppError(
                    ErrorCode.VALIDATION_FAILED,
                    message,
                    errors=[FieldError(field="cover_media_id", code=problem, message=message)],
                )
        row.cover_media_id = cover_media_id
        changed.append("cover")
    if is_featured is not None and row.is_featured != is_featured:
        row.is_featured = is_featured
        changed.append("is_featured")
    if status is not None and row.status != status:
        row.status = status
        changed.append("status")
    await session.flush()
    if changed:
        platform.record_event(
            session,
            aggregate_type="destination",
            aggregate_id=row.id,
            event_type="destination.updated",
            payload={
                "destination_id": str(row.id),
                "slug": row.slug,
                "changed": changed,
                "status": row.status,
                "is_featured": row.is_featured,
            },
        )
    return await _detail(session, row, ("en",))


__all__ = [
    "PLACE_STALE_AFTER",
    "DestinationService",
    "ListFilters",
    "PlaceCandidate",
    "PlaceService",
    "admin_update",
    "place_candidates",
    "place_destination",
    "place_ids_within",
    "place_is_listed",
    "place_summaries",
    "set_has_guides",
]
