"""The six location concepts live in separate storage (LOC-001, ERD §4).

Home, current device, selected browse destination, post destination, trip destination and
traveller discovery each have their own table or columns and lifecycle; there is no shared
"user location" that one feature could read from another.
"""

from __future__ import annotations

import pytest

import app.main  # noqa: F401 - registers every model
from app.core.db import Base

pytestmark = pytest.mark.req("LOC-001", "NFR-007")

TABLES = Base.metadata.tables

# Catalog data with coordinates; no user-owned table stores coordinates (T-LOC-01).
CATALOG_WITH_COORDINATES = {"destinations", "places"}


def _columns(table: str) -> set[str]:
    return {column.name for column in TABLES[table].columns}


def test_each_concept_has_its_own_storage() -> None:
    assert {"home_country_code", "home_region"} <= _columns("user_profiles")  # home
    assert {"user_id", "kind", "destination_id"} <= _columns("user_selected_locations")  # browse
    assert "primary_destination_id" in _columns("posts")  # post destination
    assert "destination_id" in _columns("post_destinations")
    assert {"trip_id", "destination_id"} <= _columns("trip_destinations")  # trip destination
    assert {"user_id", "destination_id", "visibility"} <= _columns("traveler_discovery_sessions")


def test_no_shared_user_location_column() -> None:
    for table in ("users", "user_profiles", "user_preferences", "user_privacy_settings"):
        generic = {c for c in _columns(table) if c in {"location", "lat", "lng", "city_id"}}
        assert not generic, (table, generic)


def test_the_current_device_location_is_never_stored() -> None:
    """Device coordinates are rounded and used per request (LOC-005); no table keeps them."""
    for name, table in TABLES.items():
        coordinates = {c.name for c in table.columns if c.name in {"lat", "lng", "latitude"}}
        if coordinates:
            assert name in CATALOG_WITH_COORDINATES, (name, coordinates)
