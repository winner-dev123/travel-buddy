"""Public request/response models (mirror contracts/openapi/openapi.yaml component schemas)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints, model_validator

from app.core.i18n import LOCALE_TAG_PATTERN

LocaleTag = Annotated[str, StringConstraints(pattern=LOCALE_TAG_PATTERN, max_length=35)]
TravelStyle = Literal[
    "adventure",
    "backpacking",
    "luxury",
    "food",
    "culture",
    "photography",
    "digital_nomad",
    "nature",
    "family",
]
NotificationType = Literal[
    "connection_request",
    "connection_accepted",
    "new_message",
    "group_invitation",
    "group_announcement",
    "challenge_started",
    "challenge_result",
    "post_reaction",
    "post_comment",
    "new_follower",
    "follow_request",
    "moderation_notice",
    "subscription_notice",
    "ai_generation_ready",
    "data_export_ready",
]
NotificationChannel = Literal["push", "in_app", "email"]
NotificationMatrix = dict[NotificationType, dict[NotificationChannel, StrictBool]]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True)


class _Patch(BaseModel):
    """PATCH body: unknown fields rejected, at least one field, and ``null`` only where the
    contract allows it (absent ≠ null)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    nullable_fields: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _check_presence(self) -> Any:
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        for name in self.model_fields_set:
            if getattr(self, name) is None and name not in self.nullable_fields:
                raise ValueError(f"{name} cannot be null")
        return self

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class UpdateMyProfileRequest(_Patch):
    nullable_fields: ClassVar[frozenset[str]] = frozenset(
        {"bio", "avatar_media_id", "home_country_code", "home_region"}
    )

    handle: str | None = Field(default=None, pattern=r"^[a-z0-9_.]{3,30}$")
    display_name: str | None = Field(default=None, min_length=1, max_length=50)
    bio: str | None = Field(default=None, max_length=300)
    avatar_media_id: uuid.UUID | None = None
    home_country_code: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    home_region: str | None = Field(default=None, max_length=100)
    travel_styles: list[TravelStyle] | None = Field(default=None, max_length=9)
    interests: list[Annotated[str, StringConstraints(max_length=40)]] | None = Field(
        default=None, max_length=20
    )
    languages_spoken: list[LocaleTag] | None = Field(default=None, max_length=10)
    account_visibility: Literal["public", "private"] | None = None


class UpdatePreferencesRequest(_Patch):
    ui_locale: LocaleTag | None = None
    content_languages: list[LocaleTag] | None = Field(default=None, max_length=10)
    time_zone: str | None = Field(default=None, max_length=64)
    currency_code: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    distance_unit: Literal["km", "mi"] | None = None
    auto_translate: StrictBool | None = None
    # Merged per notification type and channel; omitted entries keep their value.
    notification_settings: NotificationMatrix | None = None


class UpdatePrivacySettingsRequest(_Patch):
    discovery_enabled: StrictBool | None = None
    discovery_granularity: Literal["city", "neighborhood"] | None = None
    connection_requests_from: Literal["everyone", "shared_context", "nobody"] | None = None
    profile_visibility: Literal["public", "connections"] | None = None
    show_trips_on_profile: StrictBool | None = None
    read_receipts_enabled: StrictBool | None = None
    post_location_default: Literal["none", "destination", "place"] | None = None
    search_engine_indexing: StrictBool | None = None


class ProfileCounts(_Model):
    posts: int = 0
    followers: int = 0
    following: int = 0


class MyProfile(_Model):
    id: uuid.UUID
    handle: str
    display_name: str
    bio: str | None
    avatar: None  # MediaRef once the media module lands (BL-1.08); always null until then
    home_country_code: str | None
    home_region: str | None
    travel_styles: list[str]
    interests: list[str]
    languages_spoken: list[str]
    account_visibility: Literal["public", "private"]
    counts: ProfileCounts
    updated_at: datetime


class Preferences(_Model):
    ui_locale: str
    content_languages: list[str]
    time_zone: str
    currency_code: str
    distance_unit: Literal["km", "mi"]
    auto_translate: bool
    # Only explicit choices are stored; clients apply defaults for missing entries.
    notification_settings: dict[str, dict[str, bool]]


class ConsentState(_Model):
    version: str
    granted_at: datetime


class PrivacySettings(_Model):
    discovery_enabled: bool
    discovery_granularity: Literal["city", "neighborhood"]
    connection_requests_from: Literal["everyone", "shared_context", "nobody"]
    profile_visibility: Literal["public", "connections"]
    show_trips_on_profile: bool
    read_receipts_enabled: bool
    post_location_default: Literal["none", "destination", "place"]
    search_engine_indexing: bool
    location_consent: ConsentState | None
    discovery_consent: ConsentState | None


class PrivacyUpdate(_Model):
    """Result of a privacy change: the new settings and which fields actually changed."""

    settings: PrivacySettings
    changed: frozenset[str]


class ProfileBundle(_Model):
    """Internal aggregate returned by ``profiles.service`` to compose ``Me``."""

    profile: MyProfile
    preferences: Preferences
    privacy: PrivacySettings
    onboarding_completed: bool
