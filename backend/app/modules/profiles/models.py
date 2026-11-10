"""Profile tables (docs/04 section 3). Private to the profiles module.

Defaults are privacy-protective by construction: discovery off, search indexing off, trips hidden.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_check


class AccountVisibility(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"


class DistanceUnit(StrEnum):
    KM = "km"
    MI = "mi"


class DiscoveryGranularity(StrEnum):
    CITY = "city"
    NEIGHBORHOOD = "neighborhood"


class ConnectionRequestsFrom(StrEnum):
    EVERYONE = "everyone"
    SHARED_CONTEXT = "shared_context"
    NOBODY = "nobody"


class ProfileVisibility(StrEnum):
    PUBLIC = "public"
    CONNECTIONS = "connections"


class LocationPrecision(StrEnum):
    NONE = "none"
    DESTINATION = "destination"
    PLACE = "place"


class UserProfile(Base):
    __tablename__ = "user_profiles"
    __table_args__ = (
        UniqueConstraint("handle"),
        enum_check("account_visibility", AccountVisibility, "account_visibility_enum"),
        Index("ix_user_profiles__travel_styles", "travel_styles", postgresql_using="gin"),
        Index("ix_user_profiles__interests", "interests", postgresql_using="gin"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    handle: Mapped[str] = mapped_column(CITEXT)
    # NULL = still the generated handle; changes are limited to one per 30 days (PROF-003).
    handle_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    display_name: Mapped[str] = mapped_column(Text)
    bio: Mapped[str | None] = mapped_column(Text)
    # FK to media_assets is added with the media module (Phase 1, BL-1.08).
    avatar_media_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    home_country_code: Mapped[str | None] = mapped_column(Text)
    home_region: Mapped[str | None] = mapped_column(Text)
    travel_styles: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    interests: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    languages_spoken: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    account_visibility: Mapped[str] = mapped_column(Text, server_default=text("'public'"))
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserPreferences(Base):
    __tablename__ = "user_preferences"
    __table_args__ = (enum_check("distance_unit", DistanceUnit, "distance_unit_enum"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    ui_locale: Mapped[str] = mapped_column(Text)
    content_languages: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    time_zone: Mapped[str] = mapped_column(Text, server_default=text("'UTC'"))
    currency_code: Mapped[str] = mapped_column(Text, server_default=text("'USD'"))
    distance_unit: Mapped[str] = mapped_column(Text, server_default=text("'km'"))
    auto_translate: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    notification_settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    # {"start": "HH:MM", "end": "HH:MM"} in time_zone, or NULL (NOTIF-003).
    quiet_hours: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserPrivacySettings(Base):
    __tablename__ = "user_privacy_settings"
    __table_args__ = (
        enum_check("discovery_granularity", DiscoveryGranularity, "discovery_granularity_enum"),
        enum_check(
            "connection_requests_from", ConnectionRequestsFrom, "connection_requests_from_enum"
        ),
        enum_check("profile_visibility", ProfileVisibility, "profile_visibility_enum"),
        enum_check("post_location_default", LocationPrecision, "post_location_default_enum"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    discovery_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    discovery_granularity: Mapped[str] = mapped_column(Text, server_default=text("'city'"))
    connection_requests_from: Mapped[str] = mapped_column(Text, server_default=text("'everyone'"))
    profile_visibility: Mapped[str] = mapped_column(Text, server_default=text("'public'"))
    show_trips_on_profile: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    read_receipts_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    post_location_default: Mapped[str] = mapped_column(Text, server_default=text("'destination'"))
    search_engine_indexing: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    location_consent_version: Mapped[str | None] = mapped_column(Text)
    location_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovery_consent_version: Mapped[str | None] = mapped_column(Text)
    discovery_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
