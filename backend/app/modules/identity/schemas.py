"""Request/response models for auth, sessions, me and the dev IdP (mirror the OpenAPI contract)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StringConstraints

from app.core.pagination import PageInfo
from app.core.security.principal import Permission, PlatformRole
from app.modules.billing.schemas import Entitlements
from app.modules.destinations.schemas import DestinationSummary
from app.modules.profiles.schemas import MyProfile, Preferences, PrivacySettings

ClientPlatform = Literal["ios", "android", "web"]
LocaleTag = Annotated[
    str, StringConstraints(pattern=r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$", max_length=35)
]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Response(BaseModel):
    model_config = ConfigDict(frozen=True)


class DeviceInfo(_Request):
    device_id: str = Field(min_length=8, max_length=128)
    device_name: str | None = Field(default=None, max_length=80)
    app_version: str | None = Field(default=None, pattern=r"^\d+\.\d+\.\d+$")


class LoginRequest(_Request):
    id_token: str = Field(min_length=20, max_length=8192)
    client: ClientPlatform
    nonce: str | None = Field(default=None, max_length=128)
    device: DeviceInfo | None = None


class RegisterRequest(LoginRequest):
    birth_date: date
    accepted_terms_version: str = Field(max_length=32)
    accepted_privacy_version: str = Field(max_length=32)
    locale: LocaleTag


class RefreshRequest(_Request):
    refresh_token: str = Field(min_length=32, max_length=512)


class LogoutRequest(_Request):
    all_sessions: bool = False


class SessionTokens(_Response):
    token_type: Literal["Bearer"] = "Bearer"  # noqa: S105 - scheme name, not a secret
    access_token: str
    access_token_expires_at: datetime
    refresh_token: str
    refresh_token_expires_at: datetime
    session_id: uuid.UUID


class AccountRestriction(_Response):
    """Contract ``AccountRestriction``: an active moderation restriction on my account."""

    kind: Literal[
        "posting_limited",
        "commenting_limited",
        "messaging_limited",
        "connection_requests_limited",
        "discovery_disabled",
        "media_upload_limited",
    ]
    reason_code: str
    until: datetime | None
    appealable: bool


class MyAccount(_Response):
    id: uuid.UUID
    email: str | None
    email_verified: bool
    status: Literal["active", "pending_deletion"]
    primary_locale: str
    age_assured: bool
    deletion_scheduled_for: datetime | None
    created_at: datetime
    restrictions: list[AccountRestriction] = Field(default_factory=list)


class Me(_Response):
    account: MyAccount
    profile: MyProfile
    preferences: Preferences
    privacy: PrivacySettings
    roles: list[PlatformRole]
    permissions: list[Permission]
    onboarding_completed: bool
    browse_destination: DestinationSummary | None
    entitlements: Entitlements


class AuthResult(_Response):
    tokens: SessionTokens
    user: Me
    is_new_user: bool


class SessionOut(_Response):
    id: uuid.UUID
    platform: ClientPlatform
    device_name: str | None
    app_version: str | None
    created_at: datetime
    last_used_at: datetime
    is_current: bool


class SessionList(_Response):
    data: list[SessionOut]


class DevIdpTokenRequest(_Request):
    sub: str = Field(min_length=1, max_length=255)
    # Syntax check only: development fixtures commonly use reserved domains such as .test,
    # which strict email validation rejects.
    email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    email_verified: bool = True
    name: str | None = Field(default=None, max_length=100)
    nonce: str | None = Field(default=None, max_length=128)
    # Simulates a completed second factor (adds RFC 8176 "mfa" to amr) for staff flows (ADM-007).
    mfa: bool = False


class DevIdpToken(_Response):
    id_token: str
    expires_at: datetime


class Jwk(_Response):
    kty: Literal["OKP"]
    crv: Literal["Ed25519"]
    x: str
    kid: str
    alg: Literal["EdDSA"]
    use: Literal["sig"]


class Jwks(_Response):
    keys: list[Jwk]


ConsentTypeName = Literal[
    "terms",
    "privacy_policy",
    "location",
    "traveler_discovery",
    "marketing",
    "ai_personalization",
    "post_translation",
    "search_indexing",
]
ConsentSourceName = Literal["onboarding", "settings", "prompt"]


class ConsentRequest(_Request):
    consent_type: ConsentTypeName
    version: str = Field(min_length=1, max_length=32)
    granted: StrictBool
    source: ConsentSourceName


class ConsentRecordOut(_Response):
    consent_type: ConsentTypeName
    version: str
    granted: bool
    source: ConsentSourceName
    recorded_at: datetime


class ConsentList(_Response):
    data: list[ConsentRecordOut]


class AccountDeletionRequest(BaseModel):
    """Contract ``AccountDeletionRequest``."""

    model_config = ConfigDict(extra="forbid")

    confirm: Literal[True]
    reason: str | None = Field(default=None, max_length=500)


class ExportDownload(_Response):
    url: str
    expires_at: datetime


class DataSubjectRequestOut(_Response):
    """Contract ``DataSubjectRequest``."""

    id: uuid.UUID
    kind: Literal["export", "deletion", "rectification"]
    status: Literal["received", "processing", "completed", "rejected", "cancelled"]
    requested_at: datetime
    completed_at: datetime | None
    scheduled_for: datetime | None = None
    download: ExportDownload | None = None


class DataSubjectRequestPage(_Response):
    data: list[DataSubjectRequestOut]
    page: PageInfo


class WebPushKeys(_Request):
    p256dh: str = Field(min_length=1, max_length=256)
    auth: str = Field(min_length=1, max_length=256)


class WebPushSubscription(_Request):
    endpoint: str = Field(pattern=r"^https://", max_length=2048)
    expiration_time: int | None = None
    keys: WebPushKeys


class NativePushRegistration(_Request):
    provider: Literal["expo", "fcm", "apns"]
    token: str = Field(min_length=8, max_length=4096)
    device_id: str = Field(min_length=8, max_length=128)


class WebPushRegistration(_Request):
    provider: Literal["webpush"]
    subscription: WebPushSubscription
    device_id: str = Field(min_length=8, max_length=128)


RegisterPushDeviceRequest = Annotated[
    NativePushRegistration | WebPushRegistration, Field(discriminator="provider")
]


class PushDeviceOut(_Response):
    """Contract ``PushDevice``: never includes the token or endpoint."""

    id: uuid.UUID
    provider: Literal["expo", "fcm", "apns", "webpush"]
    device_id: str
    created_at: datetime
    last_seen_at: datetime
