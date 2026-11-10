"""OSM boundary relations become valid multipolygons (DEST-005, ADR-0027)."""

from __future__ import annotations

import pytest

from app.modules.destinations.boundaries import (
    BoundaryError,
    assemble_rings,
    license_of,
    multipolygon_wkt,
    relation_wkt,
    ring_contains,
)

pytestmark = pytest.mark.req("DEST-005")

SQUARE = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0), (0.0, 0.0)]


def test_ways_are_joined_end_to_end_whatever_their_direction() -> None:
    south = [(0.0, 0.0), (4.0, 0.0)]
    east = [(4.0, 4.0), (4.0, 0.0)]  # reversed
    north = [(4.0, 4.0), (0.0, 4.0)]
    west = [(0.0, 0.0), (0.0, 4.0)]  # reversed
    [ring] = assemble_rings([south, north, east, west])
    assert ring[0] == ring[-1]
    assert sorted(set(ring)) == sorted(set(SQUARE))
    assert len(ring) == 5


def test_open_or_degenerate_rings_are_refused() -> None:
    with pytest.raises(BoundaryError, match="does not close"):
        assemble_rings([[(0.0, 0.0), (1.0, 0.0)], [(5.0, 5.0), (6.0, 6.0)]])
    with pytest.raises(BoundaryError, match="three corners"):
        assemble_rings([[(0.0, 0.0), (1.0, 0.0), (0.0, 0.0)]])


def test_holes_go_into_the_outer_ring_that_contains_them() -> None:
    hole = [(1.0, 1.0), (2.0, 1.0), (2.0, 2.0), (1.0, 2.0), (1.0, 1.0)]
    island = [(10.0, 10.0), (11.0, 10.0), (11.0, 11.0), (10.0, 10.0)]
    stray = [(20.0, 20.0), (21.0, 20.0), (21.0, 21.0), (20.0, 20.0)]
    assert ring_contains(SQUARE, (1.0, 1.0))
    assert not ring_contains(SQUARE, (10.0, 10.0))
    wkt = multipolygon_wkt([SQUARE, island], [hole, stray])
    assert wkt.startswith("MULTIPOLYGON(((0.0 0.0,")
    assert "),(1.0 1.0," in wkt  # the hole follows the square's outer ring
    assert "20.0 20.0" not in wkt  # a hole outside every outer ring is dropped
    assert wkt.count("((") == 2  # two polygons


def test_an_overpass_relation_becomes_wkt() -> None:
    def way(role: str, points: list[tuple[float, float]]) -> dict[str, object]:
        return {
            "type": "way",
            "role": role,
            "geometry": [{"lat": lat, "lon": lon} for lon, lat in points],
        }

    element = {
        "type": "relation",
        "id": 62422,
        "members": [
            way("outer", [(13.0, 52.0), (14.0, 52.0), (14.0, 53.0)]),
            way("outer", [(14.0, 53.0), (13.0, 53.0), (13.0, 52.0)]),
            {"type": "node", "role": "admin_centre", "lat": 52.5, "lon": 13.4},
            way("inner", [(13.4, 52.4), (13.6, 52.4), (13.6, 52.6), (13.4, 52.4)]),
        ],
    }
    wkt = relation_wkt(element)
    assert wkt.count("((") == 1
    assert "13.4 52.4" in wkt
    with pytest.raises(BoundaryError, match="no outer ring"):
        relation_wkt({"type": "relation", "id": 1, "members": []})


def test_the_license_of_each_source_is_known() -> None:
    assert license_of("osm:62422") == "ODbL-1.0"
    assert license_of("approximate-bbox") == "none (own)"
    assert license_of("unknown") is None
