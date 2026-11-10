"""Pure destination rules and the integrity of the launch catalog (BL-1.05)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.i18n import parse_accept_language
from app.modules.destinations.domain import (
    SEGMENT_PATTERN,
    BoundingBox,
    Point,
    StaleLocationError,
    check_fix_age,
    city_level_only,
    localized,
    parse_near,
)
from app.modules.destinations.seeding import read_document, slug_for

NAMES = {"en": "Lisbon", "pt-BR": "Lisboa", "de": "Lissabon", "fr": "Lisbonne"}


@pytest.mark.req("DEST-002")
@pytest.mark.parametrize(
    ("preferences", "expected"),
    [
        (["de"], "Lissabon"),
        (["pt-BR"], "Lisboa"),
        (["pt-PT", "en"], "Lisboa"),  # same language beats the English fallback
        (["ja"], "Lisbon"),
        ([], "Lisbon"),
        (["FR-ca"], "Lisbonne"),
    ],
)
def test_localized_name_fallback(preferences: list[str], expected: str) -> None:
    assert localized(NAMES, preferences) == expected


def test_localized_returns_none_without_any_match() -> None:
    assert localized({"de": "Lissabon"}, ["ja"]) is None


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("de-DE,de;q=0.9,en;q=0.8", ["de-DE", "de", "en"]),
        ("en;q=0.5, pt-BR", ["pt-BR", "en"]),
        ("*;q=0.1, fr;q=0", []),
        (None, []),
        ("es;q=abc, it", ["it"]),
    ],
)
def test_accept_language_parsing(header: str | None, expected: list[str]) -> None:
    assert parse_accept_language(header) == expected


@pytest.mark.req("LOC-003")
@pytest.mark.security
def test_near_is_rounded_to_about_110_m() -> None:
    assert parse_near("-22.971123,-43.182987") == Point(-22.971, -43.183)
    for bad in ("91,0", "0,181", "abc", "1;2", "-22.9"):
        with pytest.raises(ValueError):
            parse_near(bad)


def test_bounding_box_validation_and_wkt() -> None:
    box = BoundingBox(south=-23.0, west=-43.8, north=-22.7, east=-43.1)
    assert box.contains(Point(-22.9, -43.2))
    assert not box.contains(Point(-22.6, -43.2))
    assert box.as_multipolygon_wkt().startswith("MULTIPOLYGON(((-43.8 -23.0, -43.1 -23.0")
    with pytest.raises(ValueError, match="latitude"):
        BoundingBox(south=1, west=0, north=0, east=1)
    with pytest.raises(ValueError, match="antimeridian"):
        BoundingBox(south=0, west=170, north=1, east=-170)


def test_slugs_are_globally_unique_and_readable() -> None:
    assert slug_for("brazil", "BR", "country") == "brazil"
    assert slug_for("brazil/rio-de-janeiro", "BR", "city") == "rio-de-janeiro-br"
    assert slug_for("brazil/rio-de-janeiro/copacabana", "BR", "neighborhood") == (
        "copacabana-rio-de-janeiro-br"
    )


@pytest.mark.req("DEST-002", "LOC-006")
def test_launch_catalog_is_consistent() -> None:
    entries = read_document()["destinations"]
    by_path = {e["path"]: e for e in entries}
    assert len(by_path) == len(entries) == 41
    slugs = {slug_for(e["path"], e["country_code"], e["kind"]) for e in entries}
    assert len(slugs) == len(entries)
    for entry in entries:
        segments = entry["path"].split("/")
        assert all(SEGMENT_PATTERN.fullmatch(s) for s in segments)
        box = BoundingBox(**entry["bbox"])
        assert box.contains(Point(entry["centroid"]["lat"], entry["centroid"]["lng"]))
        assert set(entry["names"]) >= {"en", "es", "pt-BR", "fr", "de"}
        if len(segments) > 1:
            parent = by_path["/".join(segments[:-1])]
            assert parent["country_code"] == entry["country_code"]
            parent_box = BoundingBox(**parent["bbox"])
            # A child's box lies inside its parent's, so resolution is hierarchical.
            assert parent_box.south <= box.south
            assert box.north <= parent_box.north
            assert parent_box.west <= box.west
            assert box.east <= parent_box.east


@pytest.mark.req("LOC-007")
def test_device_fixes_older_than_15_minutes_are_stale() -> None:
    now = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
    check_fix_age(None, now)  # older clients send no timestamp
    check_fix_age(now - timedelta(minutes=15), now)
    check_fix_age(now + timedelta(minutes=1), now)  # small clock skew
    with pytest.raises(StaleLocationError):
        check_fix_age(now - timedelta(minutes=15, seconds=1), now)
    with pytest.raises(ValueError, match="future"):
        check_fix_age(now + timedelta(minutes=3), now)
    # A timestamp without an offset is read as UTC instead of failing the comparison.
    check_fix_age(datetime(2026, 11, 10, 11, 55), now)  # noqa: DTZ001 - naive on purpose
    with pytest.raises(StaleLocationError):
        check_fix_age(datetime(2026, 11, 10, 11, 0), now)  # noqa: DTZ001


@pytest.mark.req("LOC-008")
def test_readings_coarser_than_5_km_are_city_level_only() -> None:
    assert city_level_only(None) is False
    assert city_level_only(30) is False
    assert city_level_only(5_000) is False
    assert city_level_only(5_001) is True
