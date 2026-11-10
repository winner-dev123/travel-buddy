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
