"""Licensed destination boundaries from OpenStreetMap (DEST-005, ADR-0027).

An administrative boundary is an OSM *relation* whose member ways (roles ``outer`` and ``inner``)
form the polygon. Overpass returns each way's geometry; the ways are joined end to end into closed
rings, each inner ring is placed in the outer ring that contains it, and the result is stored as a
MULTIPOLYGON repaired by PostGIS (``ST_MakeValid``). The ``source`` column records where it came
from (``osm:<relation id>``), and ``BOUNDARY_LICENSES`` maps that to its license.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

Point = tuple[float, float]  # (lng, lat), WKT order
Ring = list[Point]

OSM_SOURCE_PREFIX = "osm:"
# Source key -> license of the stored polygon. The seed's bounding boxes are our own approximation.
BOUNDARY_LICENSES: Mapping[str, str] = {"osm": "ODbL-1.0", "approximate-bbox": "none (own)"}
_DECIMALS = 6  # ~0.1 m


class BoundaryError(Exception):
    """The relation could not be turned into a polygon."""


def license_of(source: str) -> str | None:
    return BOUNDARY_LICENSES.get(source.split(":", 1)[0])


def assemble_rings(segments: Sequence[Sequence[Point]]) -> list[Ring]:
    """Join way segments end to end (reversing them as needed) into closed rings."""
    pending = [list(segment) for segment in segments if len(segment) >= 2]
    rings: list[Ring] = []
    while pending:
        ring = pending.pop(0)
        while ring[0] != ring[-1]:
            for index, segment in enumerate(pending):
                if segment[0] == ring[-1]:
                    ring.extend(segment[1:])
                elif segment[-1] == ring[-1]:
                    ring.extend(reversed(segment[:-1]))
                elif segment[-1] == ring[0]:
                    ring[:0] = segment[:-1]
                elif segment[0] == ring[0]:
                    ring[:0] = list(reversed(segment[1:]))
                else:
                    continue
                pending.pop(index)
                break
            else:
                raise BoundaryError("a boundary ring does not close")
        if len(ring) < 4:
            raise BoundaryError("a boundary ring has fewer than three corners")
        rings.append(ring)
    return rings


def ring_contains(ring: Ring, point: Point) -> bool:
    """Even-odd ray casting; good enough to place holes inside their outer ring."""
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in pairwise(ring):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def multipolygon_wkt(outers: Sequence[Ring], inners: Sequence[Ring]) -> str:
    if not outers:
        raise BoundaryError("the boundary has no outer ring")
    polygons: list[list[Ring]] = [[list(outer)] for outer in outers]
    for inner in inners:
        host = next((p for p in polygons if ring_contains(p[0], inner[0])), None)
        if host is not None:  # a hole outside every outer ring is meaningless: drop it
            host.append(list(inner))

    def ring_text(ring: Ring) -> str:
        return "(" + ",".join(f"{round(x, _DECIMALS)} {round(y, _DECIMALS)}" for x, y in ring) + ")"

    return (
        "MULTIPOLYGON("
        + ",".join("(" + ",".join(ring_text(r) for r in polygon) + ")" for polygon in polygons)
        + ")"
    )


def relation_wkt(element: Mapping[str, Any]) -> str:
    """WKT for an Overpass ``out geom`` relation element."""
    outer: list[list[Point]] = []
    inner: list[list[Point]] = []
    for member in element.get("members", []):
        if member.get("type") != "way" or not member.get("geometry"):
            continue
        points = [(float(p["lon"]), float(p["lat"])) for p in member["geometry"]]
        (inner if member.get("role") == "inner" else outer).append(points)
    return multipolygon_wkt(assemble_rings(outer), assemble_rings(inner))


class OverpassBoundarySource:
    """Boundary relations from the Overpass API (OpenStreetMap, ODbL 1.0)."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        endpoint: str = "https://overpass-api.de/api/interpreter",
        user_agent: str = "TravelBuddy/1.0 (destination boundary ingestion)",
    ) -> None:
        self._http = http_client
        self._endpoint = endpoint
        self._user_agent = user_agent

    async def fetch(self, relation_id: int) -> str:
        query = f"[out:json][timeout:120];relation({int(relation_id)});out geom;"
        try:
            response = await self._http.post(
                self._endpoint,
                data={"data": query},
                headers={"User-Agent": self._user_agent},
                timeout=150.0,
            )
        except httpx.HTTPError as exc:
            raise BoundaryError("Overpass unreachable") from exc
        if response.status_code != 200:
            raise BoundaryError(f"Overpass answered {response.status_code}")
        try:
            elements = response.json().get("elements", [])
        except ValueError as exc:
            raise BoundaryError("Overpass sent malformed JSON") from exc
        relation = next(
            (e for e in elements if e.get("type") == "relation" and e.get("id") == relation_id),
            None,
        )
        if relation is None:
            raise BoundaryError(f"relation {relation_id} not found")
        return relation_wkt(relation)


async def store_boundary(
    session: AsyncSession, destination_id: Any, wkt: str, *, source: str
) -> None:
    """Upsert a destination's polygon (PostGIS required); invalid rings are repaired, and only
    the polygon parts are kept."""
    await session.execute(
        text(
            """
            INSERT INTO destination_boundaries (destination_id, boundary, source)
            VALUES (
                :id,
                ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_GeomFromText(:wkt, 4326)), 3))
                    ::geography,
                :source
            )
            ON CONFLICT (destination_id) DO UPDATE
               SET boundary = EXCLUDED.boundary, source = EXCLUDED.source, updated_at = now()
            """
        ),
        {"id": destination_id, "wkt": wkt, "source": source},
    )
