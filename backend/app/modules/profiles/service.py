"""Public interface of the profiles module.

Every function runs inside the caller's session/transaction. Identity (layer above) composes
these into the ``/v1/users/me`` endpoints and owns the consent ledger.
"""

from __future__ import annotations

import secrets
import uuid
import zoneinfo
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import cache
from typing import Any

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.i18n import SUPPORTED_LOCALES, negotiate_ui_locale
from app.modules.platform import service as platform_service
from app.modules.profiles.domain import (
    BIO_MAX,
    HOME_REGION_MAX,
    INTEREST_MAX,
    clean_display_name,
    clean_optional_text,
    clean_tags,
    dedupe,
    default_display_name,
    handle_base,
    handle_with_suffix,
    is_reserved_handle,
    next_handle_change_at,
)
from app.modules.profiles.models import UserPreferences, UserPrivacySettings, UserProfile
from app.modules.profiles.schemas import (
    ConsentState,
    MyProfile,
    Preferences,
    PrivacySettings,
    PrivacyUpdate,
    ProfileBundle,
    ProfileCounts,
    UpdateMyProfileRequest,
    UpdatePreferencesRequest,
    UpdatePrivacySettingsRequest,
    UserSummary,
)

_HANDLE_ATTEMPTS = 8

# Public-facing fields: a change must reach caches and indexes (SAFE-012, BL-1.25).
_PUBLIC_PROFILE_FIELDS = frozenset(
    {
        "handle",
        "display_name",
        "bio",
        "avatar_media_id",
        "home_country_code",
        "home_region",
        "travel_styles",
        "interests",
        "languages_spoken",
        "account_visibility",
    }
)
_PUBLIC_PRIVACY_FIELDS = frozenset(
    {"profile_visibility", "search_engine_indexing", "show_trips_on_profile"}
)


async def _handle_taken(session: AsyncSession, handle: str) -> bool:
    return bool(await session.scalar(select(exists().where(UserProfile.handle == handle))))


async def create_default_profile(
    session: AsyncSession, *, user_id: uuid.UUID, idp_name: str | None, locale: str
) -> None:
    """Create profile, preferences and privacy rows with protective defaults.

    Runs inside the caller's transaction. Handle collisions (including races) are retried with
    a random numeric suffix inside a savepoint.
    """
    base = handle_base(idp_name)
    candidates = [base] if len(base) >= 3 and base != "traveler" else []
    candidates += [
        handle_with_suffix(base, secrets.randbelow(9000) + 1000) for _ in range(_HANDLE_ATTEMPTS)
    ]
    for handle in candidates:
        if is_reserved_handle(handle) or await _handle_taken(session, handle):
            continue
        try:
            async with session.begin_nested():
                session.add(
                    UserProfile(
                        user_id=user_id,
                        handle=handle,
                        display_name=default_display_name(idp_name),
                        account_visibility="public",
                    )
                )
        except IntegrityError:
            continue  # lost a race for this handle; try the next candidate
        break
    else:  # pragma: no cover - 9 random 4-digit suffixes all colliding is practically impossible
        raise RuntimeError("could not allocate a unique handle")

    session.add(UserPreferences(user_id=user_id, ui_locale=negotiate_ui_locale(locale)))
    session.add(UserPrivacySettings(user_id=user_id))
    await session.flush()


def _consent(version: str | None, at: object) -> ConsentState | None:
    if version is None or at is None:
        return None
    return ConsentState.model_validate({"version": version, "granted_at": at})


def _notification_matrix(stored: dict[str, Any] | None) -> dict[str, dict[str, bool]]:
    return {
        kind: {channel: value for channel, value in channels.items() if isinstance(value, bool)}
        for kind, channels in (stored or {}).items()
        if isinstance(channels, dict)
    }


async def _rows(
    session: AsyncSession, user_id: uuid.UUID, *, for_update: bool = False
) -> tuple[UserProfile, UserPreferences, UserPrivacySettings]:
    profile = await session.get(UserProfile, user_id, with_for_update=for_update)
    preferences = await session.get(UserPreferences, user_id, with_for_update=for_update)
    privacy = await session.get(UserPrivacySettings, user_id, with_for_update=for_update)
    if profile is None or preferences is None or privacy is None:
        raise LookupError(f"profile rows missing for user {user_id}")
    return profile, preferences, privacy


async def get_profile_bundle(session: AsyncSession, user_id: uuid.UUID) -> ProfileBundle:
    profile, preferences, privacy = await _rows(session, user_id)
    return ProfileBundle(
        profile=MyProfile(
            id=profile.user_id,
            handle=profile.handle,
            display_name=profile.display_name,
            bio=profile.bio,
            avatar=None,
            home_country_code=profile.home_country_code,
            home_region=profile.home_region,
            travel_styles=list(profile.travel_styles),
            interests=list(profile.interests),
            languages_spoken=list(profile.languages_spoken),
            account_visibility="private" if profile.account_visibility == "private" else "public",
            # Social counters arrive with the social module (BL-1.11); zero until then.
            counts=ProfileCounts(),
            updated_at=profile.updated_at,
        ),
        preferences=Preferences(
            ui_locale=preferences.ui_locale,
            content_languages=list(preferences.content_languages),
            time_zone=preferences.time_zone,
            currency_code=preferences.currency_code,
            distance_unit="mi" if preferences.distance_unit == "mi" else "km",
            auto_translate=preferences.auto_translate,
            notification_settings=_notification_matrix(preferences.notification_settings),
        ),
        privacy=PrivacySettings.model_validate(
            {
                "discovery_enabled": privacy.discovery_enabled,
                "discovery_granularity": privacy.discovery_granularity,
                "connection_requests_from": privacy.connection_requests_from,
                "profile_visibility": privacy.profile_visibility,
                "show_trips_on_profile": privacy.show_trips_on_profile,
                "read_receipts_enabled": privacy.read_receipts_enabled,
                "post_location_default": privacy.post_location_default,
                "search_engine_indexing": privacy.search_engine_indexing,
                "location_consent": _consent(
                    privacy.location_consent_version, privacy.location_consent_at
                ),
                "discovery_consent": _consent(
                    privacy.discovery_consent_version, privacy.discovery_consent_at
                ),
            }
        ),
        onboarding_completed=profile.onboarding_completed_at is not None,
    )


# ─────────────────────────────── edits (BL-1.04) ───────────────────────────────


def _invalid(field: str, code: str, message: str) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_FAILED,
        message,
        errors=[FieldError(field=f"/{field}", code=code, message=message)],
    )


def _clean_or_422(field: str, clean: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return clean(*args, **kwargs)
    except ValueError as exc:
        raise _invalid(field, "invalid", str(exc)) from exc


def _handle_change_error(allowed_from: datetime) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_FAILED,
        "You can change your handle once every 30 days.",
        errors=[
            FieldError(
                field="/handle",
                code="change_too_soon",
                message=f"Next change allowed after {allowed_from.isoformat()}.",
            )
        ],
        extensions={"next_change_at": allowed_from.isoformat()},
    )


async def _apply_handle(
    session: AsyncSession, profile: UserProfile, handle: str, *, now: datetime
) -> bool:
    if handle == profile.handle.lower():
        return False
    if is_reserved_handle(handle):
        raise _invalid("handle", "reserved", "This handle is reserved. Choose another one.")
    allowed_from = next_handle_change_at(profile.handle_changed_at)
    if allowed_from is not None and now < allowed_from:
        raise _handle_change_error(allowed_from)
    if await _handle_taken(session, handle):
        raise AppError(ErrorCode.CONFLICT, "This handle is already taken.")
    profile.handle = handle
    profile.handle_changed_at = now
    return True


def _profile_values(changes: dict[str, Any]) -> dict[str, Any]:
    """Normalize the non-handle PATCH fields (raises 422 for unusable values)."""
    values: dict[str, Any] = {}
    if "display_name" in changes:
        values["display_name"] = _clean_or_422(
            "display_name", clean_display_name, changes["display_name"]
        )
    if "bio" in changes:
        values["bio"] = _clean_or_422(
            "bio", clean_optional_text, changes["bio"], max_length=BIO_MAX, multiline=True
        )
    if "avatar_media_id" in changes:
        if changes["avatar_media_id"] is not None:
            # Uploads arrive with the media pipeline (BL-1.08); no media can be referenced yet.
            raise _invalid("avatar_media_id", "not_found", "Media not found.")
        values["avatar_media_id"] = None
    if "home_country_code" in changes:
        values["home_country_code"] = changes["home_country_code"]
    if "home_region" in changes:
        values["home_region"] = _clean_or_422(
            "home_region",
            clean_optional_text,
            changes["home_region"],
            max_length=HOME_REGION_MAX,
            multiline=False,
        )
    if "travel_styles" in changes:
        values["travel_styles"] = dedupe(changes["travel_styles"])
    if "interests" in changes:
        values["interests"] = _clean_or_422(
            "interests", clean_tags, changes["interests"], max_length=INTEREST_MAX
        )
    if "languages_spoken" in changes:
        values["languages_spoken"] = dedupe(changes["languages_spoken"])
    if "account_visibility" in changes:
        values["account_visibility"] = changes["account_visibility"]
    return values


async def update_profile(
    session: AsyncSession, user_id: uuid.UUID, request: UpdateMyProfileRequest, *, now: datetime
) -> None:
    """Apply a profile PATCH (PROF-001/003/004). Emits ``profile.updated`` for public fields."""
    profile, _, _ = await _rows(session, user_id, for_update=True)
    changes = request.changes()
    old_handle = profile.handle
    changed: set[str] = set()
    if "handle" in changes and await _apply_handle(session, profile, changes["handle"], now=now):
        changed.add("handle")
    for field, value in _profile_values(changes).items():
        if getattr(profile, field) != value:
            setattr(profile, field, value)
            changed.add(field)
    if not changed:
        return
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:  # lost a race for the handle
        raise AppError(ErrorCode.CONFLICT, "This handle is already taken.") from exc
    public = sorted(changed & _PUBLIC_PROFILE_FIELDS)
    if public:
        # Handles are public: consumers (web cache purge) need no read-back.
        payload: dict[str, Any] = {
            "user_id": str(user_id),
            "handle": profile.handle,
            "changed": public,
        }
        if "handle" in changed:
            payload["previous_handle"] = old_handle  # public anyway; lets caches purge old URLs
        platform_service.record_event(
            session,
            aggregate_type="user",
            aggregate_id=user_id,
            event_type="profile.updated",
            payload=payload,
        )


@cache
def _time_zones() -> frozenset[str]:
    return frozenset(zoneinfo.available_timezones())


async def update_preferences(
    session: AsyncSession, user_id: uuid.UUID, request: UpdatePreferencesRequest
) -> Preferences:
    """Apply a preferences PATCH (PROF-006, I18N-002). Notification settings are merged."""
    _, preferences, _ = await _rows(session, user_id, for_update=True)
    changes = request.changes()
    if "ui_locale" in changes and changes["ui_locale"] not in SUPPORTED_LOCALES:
        raise _invalid(
            "ui_locale", "unsupported", f"Supported UI languages: {', '.join(SUPPORTED_LOCALES)}."
        )
    if "time_zone" in changes and changes["time_zone"] not in _time_zones():
        raise _invalid("time_zone", "unknown", "Use an IANA time zone such as Europe/Lisbon.")
    for field in ("ui_locale", "time_zone", "currency_code", "distance_unit", "auto_translate"):
        if field in changes:
            setattr(preferences, field, changes[field])
    if "content_languages" in changes:
        preferences.content_languages = dedupe(changes["content_languages"])
    if "notification_settings" in changes:
        merged = _notification_matrix(preferences.notification_settings)
        for kind, channels in changes["notification_settings"].items():
            merged[kind] = {**merged.get(kind, {}), **channels}
        preferences.notification_settings = merged
    await session.flush()
    return (await get_profile_bundle(session, user_id)).preferences


async def update_privacy(
    session: AsyncSession, user_id: uuid.UUID, request: UpdatePrivacySettingsRequest
) -> PrivacyUpdate:
    """Apply a privacy PATCH (PROF-007/008, DISC-001/002).

    Enabling discovery needs a current ``traveler_discovery`` consent. Recording the
    ``search_indexing`` consent for an indexing change is the caller's job (identity owns the
    consent ledger); the returned ``changed`` set says when.
    """
    profile, _, privacy = await _rows(session, user_id, for_update=True)
    changes = request.changes()
    if changes.get("discovery_enabled") is True and privacy.discovery_consent_version is None:
        raise AppError(
            ErrorCode.CONSENT_REQUIRED,
            "Turning on traveler discovery needs your consent first.",
            extensions={"consent_type": "traveler_discovery"},
        )
    changed = {field for field, value in changes.items() if getattr(privacy, field) != value}
    for field in changed:
        setattr(privacy, field, changes[field])
    await session.flush()
    _privacy_events(session, user_id, profile.handle, changed, privacy)
    settings = (await get_profile_bundle(session, user_id)).privacy
    return PrivacyUpdate(settings=settings, changed=frozenset(changed))


def _privacy_events(
    session: AsyncSession,
    user_id: uuid.UUID,
    handle: str,
    changed: set[str],
    privacy: UserPrivacySettings,
) -> None:
    if "discovery_enabled" in changed and not privacy.discovery_enabled:
        # The discovery module (Phase 2) ends active discovery sessions on this event (DISC-002).
        platform_service.record_event(
            session,
            aggregate_type="user",
            aggregate_id=user_id,
            event_type="discovery.disabled",
            payload={"user_id": str(user_id)},
        )
    visible = sorted(changed & _PUBLIC_PRIVACY_FIELDS)
    if visible:
        platform_service.record_event(
            session,
            aggregate_type="user",
            aggregate_id=user_id,
            event_type="privacy.updated",
            payload={"user_id": str(user_id), "handle": handle, "changed": visible},
        )


async def apply_consent(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    consent_type: str,
    granted: bool,
    version: str,
    at: datetime,
) -> None:
    """Mirror a recorded consent into privacy settings (the ledger lives in identity).

    Withdrawing ``traveler_discovery`` turns discovery off; ``search_indexing`` is the indexing
    switch itself (PROF-008). Other consent types have no settings to mirror.
    """
    profile, _, privacy = await _rows(session, user_id, for_update=True)
    changed: set[str] = set()
    if consent_type == "location":
        privacy.location_consent_version = version if granted else None
        privacy.location_consent_at = at if granted else None
    elif consent_type == "traveler_discovery":
        privacy.discovery_consent_version = version if granted else None
        privacy.discovery_consent_at = at if granted else None
        if not granted and privacy.discovery_enabled:
            privacy.discovery_enabled = False
            changed.add("discovery_enabled")
    elif consent_type == "search_indexing" and privacy.search_engine_indexing != granted:
        privacy.search_engine_indexing = granted
        changed.add("search_engine_indexing")
    await session.flush()
    _privacy_events(session, user_id, profile.handle, changed, privacy)


async def complete_onboarding(session: AsyncSession, user_id: uuid.UUID, *, now: datetime) -> None:
    """Mark onboarding done (idempotent). Only display name and language are mandatory
    (PROF-001); the handle always exists because registration generates one."""
    profile, preferences, _ = await _rows(session, user_id, for_update=True)
    missing = [
        FieldError(field=f"/{name}", code="required", message=f"{name} is required.")
        for name, value in (
            ("handle", profile.handle),
            ("display_name", profile.display_name),
            ("ui_locale", preferences.ui_locale),
        )
        if not value
    ]
    if missing:
        raise AppError(
            ErrorCode.VALIDATION_FAILED, "Complete the required steps first.", errors=missing
        )
    if profile.onboarding_completed_at is None:
        profile.onboarding_completed_at = now
        await session.flush()
        platform_service.record_event(
            session,
            aggregate_type="user",
            aggregate_id=user_id,
            event_type="user.onboarding_completed",
            payload={"user_id": str(user_id)},
        )


async def has_discovery_consent(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """A current ``traveler_discovery`` consent (mirrored from the identity consent ledger)."""
    privacy = await session.get(UserPrivacySettings, user_id)
    return privacy is not None and privacy.discovery_consent_version is not None


@dataclass(frozen=True, slots=True)
class AuthorInfo:
    """What other modules may know about a user: public identity plus visibility flags."""

    id: uuid.UUID
    handle: str
    display_name: str
    account_private: bool
    search_engine_indexing: bool
    ui_locale: str


async def authors(
    session: AsyncSession, user_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, AuthorInfo]:
    if not user_ids:
        return {}
    rows = await session.execute(
        select(
            UserProfile.user_id,
            UserProfile.handle,
            UserProfile.display_name,
            UserProfile.account_visibility,
            UserPrivacySettings.search_engine_indexing,
            UserPreferences.ui_locale,
        )
        .join(UserPrivacySettings, UserPrivacySettings.user_id == UserProfile.user_id)
        .join(UserPreferences, UserPreferences.user_id == UserProfile.user_id)
        .where(UserProfile.user_id.in_(set(user_ids)))
    )
    return {
        row.user_id: AuthorInfo(
            id=row.user_id,
            handle=row.handle,
            display_name=row.display_name,
            account_private=row.account_visibility == "private",
            search_engine_indexing=row.search_engine_indexing,
            ui_locale=row.ui_locale,
        )
        for row in rows
    }


def user_summary(author: AuthorInfo) -> UserSummary:
    return UserSummary(id=author.id, handle=author.handle, display_name=author.display_name)
