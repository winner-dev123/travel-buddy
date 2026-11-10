"""Destination tables (docs/04 section 4). Private to the destinations module.

The centroid is stored as plain latitude/longitude columns, so the catalog, hierarchy and search
work on any PostgreSQL. Boundaries (the only PostGIS-dependent data) live in their own table and
are used solely for point -> destination resolution (LOC-005).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    Float,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_check
from app.core.ids import uuid7


class DestinationKind(StrEnum):
    COUNTRY = "country"
    ADMIN_REGION = "admin_region"
    CITY = "city"
    DISTRICT = "district"
    NEIGHBORHOOD = "neighborhood"
    AREA = "area"


class Continent(StrEnum):
    AFRICA = "africa"
    ASIA = "asia"
    EUROPE = "europe"
    MIDDLE_EAST = "middle_east"
    NORTH_AMERICA = "north_america"
    CENTRAL_AMERICA_CARIBBEAN = "central_america_caribbean"
    SOUTH_AMERICA = "south_america"
    OCEANIA = "oceania"


class DestinationStatus(StrEnum):
    ACTIVE = "active"
    HIDDEN = "hidden"


class Destination(Base):
    __tablename__ = "destinations"
    __table_args__ = (
        enum_check("kind", DestinationKind, "kind_enum"),
        enum_check("continent", Continent, "continent_enum"),
        enum_check("status", DestinationStatus, "status_enum"),
        Index("uq_destinations__slug", "slug", unique=True),
        Index(
            "uq_destinations__sibling_segment",
            text("COALESCE(parent_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            "path_segment",
            unique=True,
        ),
        Index("ix_destinations__parent", "parent_id"),
        Index(
            "uq_destinations__geonames_id",
            "geonames_id",
            unique=True,
            postgresql_where=text("geonames_id IS NOT NULL"),
        ),
        Index(
            "uq_destinations__osm_relation_id",
            "osm_relation_id",
            unique=True,
            postgresql_where=text("osm_relation_id IS NOT NULL"),
        ),
        Index(
            "uq_destinations__wikidata_id",
            "wikidata_id",
            unique=True,
            postgresql_where=text("wikidata_id IS NOT NULL"),
        ),
        Index("ix_destinations__path", "path", postgresql_using="gin"),
        Index(
            "ix_destinations__directory",
            "continent",
            text("popularity_score DESC"),
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("destinations.id", ondelete="RESTRICT")
    )
    kind: Mapped[str] = mapped_column(Text)
    country_code: Mapped[str] = mapped_column(Text)
    continent: Mapped[str] = mapped_column(Text)
    # Editorial media with verified rights only (DEST-007), checked when set and again on every
    # read, so a revoked or deleted asset simply shows no cover. No FK on purpose: media rows
    # hang off users, and the catalog must not be reachable from the user graph.
    cover_media_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    slug: Mapped[str] = mapped_column(Text)
    path_segment: Mapped[str] = mapped_column(Text)
    default_name: Mapped[str] = mapped_column(Text)
    centroid_lat: Mapped[float] = mapped_column(Double)
    centroid_lng: Mapped[float] = mapped_column(Double)
    time_zone: Mapped[str] = mapped_column(Text)
    # Ancestor IDs root -> self (cheap ancestor/descendant queries, LOC-006).
    path: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid))
    depth: Mapped[int] = mapped_column(SmallInteger)
    geonames_id: Mapped[int | None] = mapped_column(BigInteger)
    osm_relation_id: Mapped[int | None] = mapped_column(BigInteger)
    wikidata_id: Mapped[str | None] = mapped_column(Text)
    popularity_score: Mapped[float] = mapped_column(Float, server_default=text("0"))
    is_featured: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    # Maintained by the guides module (Phase 4) through events; false until then.
    has_guides: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DestinationLocalization(Base):
    __tablename__ = "destination_localizations"
    # The trigram index on f_unaccent(lower(name)) is created by migration 0005 (expression index).
    __table_args__ = (CheckConstraint("char_length(tagline) <= 140", name="tagline_length"),)

    destination_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("destinations.id", ondelete="CASCADE"), primary_key=True
    )
    locale: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    alt_names: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    tagline: Mapped[str | None] = mapped_column(Text)


class DestinationBoundary(Base):
    """PostGIS-only: polygons for ``ST_Covers`` point resolution (LOC-005)."""

    __tablename__ = "destination_boundaries"
    __table_args__ = (
        Index("ix_destination_boundaries__boundary", "boundary", postgresql_using="gist"),
    )

    destination_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("destinations.id", ondelete="CASCADE"), primary_key=True
    )
    boundary: Mapped[object] = mapped_column(
        Geography(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False)
    )
    # Where the polygon came from, e.g. "approximate-bbox" or "osm:<relation>" (license key).
    source: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


PLACE_CATEGORIES = (
    "attraction",
    "restaurant",
    "cafe",
    "bar",
    "museum",
    "beach",
    "trail",
    "viewpoint",
    "park",
    "market",
    "lodging",
    "transit_hub",
    "other",
)
PLACE_STATUSES = ("active", "closed_permanently", "hidden")


class Place(Base):
    """A public place from a licensed source (BL-4.01, DEST-003). Like destination centroids, the
    position is plain latitude/longitude (a public place, never a user position), so nearby search
    works without PostGIS: a bounding-box prefilter on the index, then great-circle distance."""

    __tablename__ = "places"
    # The trigram index on f_unaccent(lower(default_name)) is created by migration 0031.
    __table_args__ = (
        UniqueConstraint("provider", "provider_place_id"),
        enum_check("category", PLACE_CATEGORIES, "category_enum"),
        enum_check("status", PLACE_STATUSES, "status_enum"),
        CheckConstraint("lat BETWEEN -90 AND 90 AND lng BETWEEN -180 AND 180", name="coordinates"),
        Index("ix_places__destination_category", "destination_id", "category"),
        Index("ix_places__lat_lng", "lat", "lng"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    # The most specific destination containing the place.
    destination_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("destinations.id", ondelete="RESTRICT"), nullable=False
    )
    category: Mapped[str] = mapped_column(Text)
    default_name: Mapped[str] = mapped_column(Text)
    lat: Mapped[float] = mapped_column(Double)
    lng: Mapped[float] = mapped_column(Double)
    address: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    provider: Mapped[str] = mapped_column(Text)
    provider_place_id: Mapped[str] = mapped_column(Text)
    license: Mapped[str] = mapped_column(Text)
    attribution_text: Mapped[str] = mapped_column(Text)
    attribution_url: Mapped[str | None] = mapped_column(Text)
    # When the provider data was last read; attributes are always shown with it.
    data_freshness_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"))
    popularity_score: Mapped[float] = mapped_column(Float, server_default=text("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlaceLocalization(Base):
    __tablename__ = "place_localizations"

    place_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("places.id", ondelete="CASCADE"), primary_key=True
    )
    locale: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
