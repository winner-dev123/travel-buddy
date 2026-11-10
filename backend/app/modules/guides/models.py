"""Guide and audio tour tables (docs/04 §10). Private to the guides module.

Content is versioned: authoring publishes a new ``version`` and retires the previous one, so a
downloaded offline copy can say which version it holds. Licensed content carries its license key
and, when the rights are time-limited, ``rights_expire_at`` (it stops being served after that).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_check
from app.core.ids import uuid7

TIERS = ("free", "premium", "purchasable")
STATUSES = ("draft", "published", "retired")


class DestinationGuide(Base):
    __tablename__ = "destination_guides"
    __table_args__ = (
        UniqueConstraint("destination_id", "locale", "slug", "version"),
        enum_check("tier", TIERS, "tier_enum"),
        enum_check("status", STATUSES, "status_enum"),
        Index("ix_destination_guides__destination_status", "destination_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    destination_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("destinations.id", ondelete="RESTRICT"), nullable=False
    )
    # Identifies one guide across its versions and locales (authoring key).
    slug: Mapped[str] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    # Structured sections (prose or FAQ), validated on load (GUIDE-006).
    content: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    tier: Mapped[str] = mapped_column(Text, server_default=text("'free'"))
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'draft'"))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    content_license: Mapped[str] = mapped_column(Text)
    attribution: Mapped[str | None] = mapped_column(Text)
    rights_expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AudioTour(Base):
    __tablename__ = "audio_tours"
    __table_args__ = (
        UniqueConstraint("destination_id", "locale", "slug", "version"),
        enum_check("tier", TIERS, "tier_enum"),
        enum_check("status", STATUSES, "status_enum"),
        Index("ix_audio_tours__destination_status", "destination_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    destination_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("destinations.id", ondelete="RESTRICT"), nullable=False
    )
    guide_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("destination_guides.id", ondelete="SET NULL")
    )
    slug: Mapped[str] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    tier: Mapped[str] = mapped_column(Text, server_default=text("'free'"))
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'draft'"))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    content_license: Mapped[str] = mapped_column(Text)
    rights_expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AudioTourStop(Base):
    __tablename__ = "audio_tour_stops"
    __table_args__ = (
        UniqueConstraint("tour_id", "sort_order"),
        CheckConstraint("trigger_radius_m BETWEEN 10 AND 1000", name="trigger_radius_range"),
        CheckConstraint("duration_s >= 0", name="duration_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    tour_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("audio_tours.id", ondelete="CASCADE"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(SmallInteger)
    place_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("places.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text)
    audio_media_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="RESTRICT"), nullable=False
    )
    transcript: Mapped[str | None] = mapped_column(Text)
    # Geofence radius, evaluated on the device only (GUIDE-005: no location goes to the server).
    trigger_radius_m: Mapped[int] = mapped_column(SmallInteger, server_default=text("50"))
    duration_s: Mapped[int] = mapped_column(Integer)


PACKAGE_KINDS = ("guide", "audio_tour", "map_region", "bundle")
PACKAGE_STATUSES = ("building", "published", "retired")


class OfflinePackage(Base):
    """A downloadable, versioned content pack (OFF-001). ``files`` lists every file with its size
    and SHA-256; the manifest built from it is signed when issued. Files live in private storage
    under ``offline/<package id>/``."""

    __tablename__ = "offline_packages"
    __table_args__ = (
        UniqueConstraint("destination_id", "locale", "kind", "version"),
        enum_check("kind", PACKAGE_KINDS, "kind_enum"),
        enum_check("status", PACKAGE_STATUSES, "status_enum"),
        enum_check("tier", TIERS, "tier_enum"),
        Index("ix_offline_packages__destination_status", "destination_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    destination_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("destinations.id", ondelete="RESTRICT"), nullable=False
    )
    locale: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    files: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    total_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(Text)
    tier: Mapped[str] = mapped_column(Text, server_default=text("'free'"))
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="SET NULL")
    )
    min_app_version: Mapped[str] = mapped_column(Text, server_default=text("'1.0.0'"))
    content_license: Mapped[str] = mapped_column(Text)
    license_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, server_default=text("'building'"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OfflinePackageLicense(Base):
    """A package licensed to one of the user's devices; active ones count against the
    ``offline.packages`` quota (OFF-004)."""

    __tablename__ = "offline_package_licenses"
    __table_args__ = (
        UniqueConstraint("user_id", "package_id", "device_id"),
        Index("ix_offline_package_licenses__user_active", "user_id", "revoked_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    package_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("offline_packages.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(Text)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
