"""Public interface of the profiles module."""

from __future__ import annotations

import secrets
import uuid

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.profiles.domain import default_display_name, handle_base, handle_with_suffix
from app.modules.profiles.models import UserPreferences, UserPrivacySettings, UserProfile
from app.modules.profiles.schemas import (
    ConsentState,
    MyProfile,
    NotificationChannelSettings,
    Preferences,
    PrivacySettings,
    ProfileBundle,
    ProfileCounts,
)

_HANDLE_ATTEMPTS = 8


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
        if await _handle_taken(session, handle):
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

    session.add(UserPreferences(user_id=user_id, ui_locale=locale))
    session.add(UserPrivacySettings(user_id=user_id))
    await session.flush()


def _consent(version: str | None, at: object) -> ConsentState | None:
    if version is None or at is None:
        return None
    return ConsentState.model_validate({"version": version, "granted_at": at})


async def get_profile_bundle(session: AsyncSession, user_id: uuid.UUID) -> ProfileBundle:
    profile = await session.get(UserProfile, user_id)
    preferences = await session.get(UserPreferences, user_id)
    privacy = await session.get(UserPrivacySettings, user_id)
    if profile is None or preferences is None or privacy is None:
        raise LookupError(f"profile rows missing for user {user_id}")
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
            notification_settings={
                k: NotificationChannelSettings.model_validate(v)
                for k, v in (preferences.notification_settings or {}).items()
            },
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
