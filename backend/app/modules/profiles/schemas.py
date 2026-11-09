"""Public response models (mirror contracts/openapi/openapi.yaml component schemas)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True)


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


class NotificationChannelSettings(_Model):
    push: bool | None = None
    in_app: bool | None = None
    email: bool | None = None


class Preferences(_Model):
    ui_locale: str
    content_languages: list[str]
    time_zone: str
    currency_code: str
    distance_unit: Literal["km", "mi"]
    auto_translate: bool
    notification_settings: dict[str, NotificationChannelSettings]


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


class ProfileBundle(_Model):
    """Internal aggregate returned by ``profiles.service`` to compose ``Me``."""

    profile: MyProfile
    preferences: Preferences
    privacy: PrivacySettings
    onboarding_completed: bool
