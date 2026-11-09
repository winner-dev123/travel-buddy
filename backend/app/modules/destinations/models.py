"""Destination tables (docs/04 section 4). Private to the destinations module.

The centroid is stored as plain latitude/longitude columns, so the catalog, hierarchy and search
work on any PostgreSQL. Boundaries (the only PostGIS-dependent data) live in their own table and
are used solely for point -> destination resolution (LOC-005).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

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
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
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
    # FK to media_assets is added with the media module (BL-1.08); editorial rights per DEST-007.
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
