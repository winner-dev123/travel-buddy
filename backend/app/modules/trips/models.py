"""Trip tables (docs/04 §4 trip_destinations, §10 trips). Private to the trips module."""

from __future__ import annotations

import datetime as dt
import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_check
from app.core.ids import uuid7

VISIBILITY = ("private", "connections", "group", "public")
ORIGIN = ("manual", "ai_generated", "ai_assisted")
STATUS = ("planning", "active", "completed", "archived")
ITEM_KINDS = ("activity", "meal", "transit", "lodging", "note", "free_time")


class Trip(Base):
    __tablename__ = "trips"
    __table_args__ = (
        enum_check("visibility", VISIBILITY, "visibility_enum"),
        enum_check("origin", ORIGIN, "origin_enum"),
        enum_check("status", STATUS, "status_enum"),
        CheckConstraint("start_date <= end_date", name="dates_order"),
        CheckConstraint("char_length(title) BETWEEN 1 AND 100", name="title_length"),
        Index("ix_trips__owner", "owner_id", text("updated_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    visibility: Mapped[str] = mapped_column(Text, server_default=text("'private'"))
    group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    origin: Mapped[str] = mapped_column(Text, server_default=text("'manual'"))
    ai_generation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(Text, server_default=text("'planning'"))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TripDestination(Base):
    __tablename__ = "trip_destinations"
    __table_args__ = (
        UniqueConstraint("trip_id", "destination_id"),
        Index("ix_trip_destinations__destination_id", "destination_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    trip_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    destination_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("destinations.id", ondelete="RESTRICT"), nullable=False
    )
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))


class TripCollaborator(Base):
    __tablename__ = "trip_collaborators"
    __table_args__ = (
        PrimaryKeyConstraint("trip_id", "user_id"),
        enum_check("role", ("editor", "viewer"), "role_enum"),
        Index("ix_trip_collaborators__user_id", "user_id"),
    )

    trip_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, server_default=text("'viewer'"))
    added_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ItineraryDay(Base):
    __tablename__ = "itinerary_days"
    __table_args__ = (UniqueConstraint("trip_id", "day_index"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    trip_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("trips.id", ondelete="CASCADE"), nullable=False
    )
    day_index: Mapped[int] = mapped_column(SmallInteger)
    date: Mapped[dt.date | None] = mapped_column(Date)
    destination_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("destinations.id", ondelete="SET NULL")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ItineraryItem(Base):
    """``sort_order`` is fractional so a move touches one row; ``deleted_at`` keeps tombstones for
    offline sync (TRIP-004)."""

    __tablename__ = "itinerary_items"
    __table_args__ = (
        enum_check("kind", ITEM_KINDS, "kind_enum"),
        enum_check("origin", ("user", "ai"), "origin_enum"),
        CheckConstraint("duration_minutes BETWEEN 0 AND 1440", name="duration_range"),
        CheckConstraint("char_length(title) BETWEEN 1 AND 120", name="title_length"),
        Index("ix_itinerary_items__day_order", "day_id", "sort_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    day_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("itinerary_days.id", ondelete="CASCADE"), nullable=False
    )
    sort_order: Mapped[Decimal] = mapped_column(Numeric(30, 15))
    kind: Mapped[str] = mapped_column(Text)
    place_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # FK arrives with places (BL-4.01)
    title: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    start_time: Mapped[time | None] = mapped_column(Time)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    origin: Mapped[str] = mapped_column(Text, server_default=text("'user'"))
    ai_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    unverified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    source_attribution: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    data_freshness_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
