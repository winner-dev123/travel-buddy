"""Feature flags for unfinished or phased capabilities.

Defaults are OFF for everything not yet production-ready. Overrides come from the
``FEATURE_FLAGS`` setting (JSON). Unknown flag names fail at boot to catch typos.

The API enforces them (BL-6.10): a route behind a disabled flag answers ``403 feature_disabled``
with ``feature_key``. Data stays readable where noted; new activity is refused.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Any

from fastapi import Depends, Request

from app.core.errors import AppError, ErrorCode


class Flag(StrEnum):
    # Phase 1
    GUEST_BROWSING = "guest_browsing"
    POST_VIDEO = "post_video"
    # Phase 2
    TRAVELER_DISCOVERY = "traveler_discovery"
    CONNECTIONS = "connections"
    # Phase 3
    DIRECT_MESSAGES = "direct_messages"
    TRAVEL_GROUPS = "travel_groups"
    GROUP_JOIN_REQUESTS = "group_join_requests"
    GROUP_PUBLIC_VISIBILITY = "group_public_visibility"
    BILLING = "billing"
    # Phase 4
    AI_ITINERARIES = "ai_itineraries"
    AI_REPLANNING = "ai_replanning"
    TRIPS = "trips"
    GUIDES = "guides"
    OFFLINE_PACKAGES = "offline_packages"
    POST_TRANSLATION = "post_translation"
    # Phase 5
    GROUP_CHALLENGES = "group_challenges"


_DEFAULTS: Mapping[Flag, bool] = dict.fromkeys(Flag, False)


class FeatureFlags:
    def __init__(self, overrides: Mapping[str, bool] | None = None) -> None:
        overrides = overrides or {}
        known = {f.value for f in Flag}
        unknown = sorted(set(overrides) - known)
        if unknown:
            raise ValueError(f"Unknown feature flag(s): {', '.join(unknown)}")
        self._values: dict[Flag, bool] = dict(_DEFAULTS)
        for name, enabled in overrides.items():
            self._values[Flag(name)] = bool(enabled)

    def is_enabled(self, flag: Flag) -> bool:
        return self._values[flag]

    def snapshot(self) -> dict[str, bool]:
        return {flag.value: enabled for flag, enabled in self._values.items()}


def feature_disabled(flag: Flag) -> AppError:
    return AppError(
        ErrorCode.FEATURE_DISABLED,
        "This feature is not available yet.",
        extensions={"feature_key": flag.value},
    )


def require_flag(flag: Flag) -> Callable[[Request], None]:
    """FastAPI dependency factory: reject requests to routes behind a disabled flag."""

    def _dependency(request: Request) -> None:
        flags: FeatureFlags = request.app.state.feature_flags
        if not flags.is_enabled(flag):
            raise feature_disabled(flag)

    return _dependency


def require_any_flag(*flags: Flag) -> Callable[[Request], None]:
    """Routes shared by several features (e.g. conversations: direct messages and group chats)."""

    def _dependency(request: Request) -> None:
        state: FeatureFlags = request.app.state.feature_flags
        if not any(state.is_enabled(flag) for flag in flags):
            raise feature_disabled(flags[0])

    return _dependency


def gate(flag: Flag) -> list[Any]:
    """``dependencies=gate(Flag.X)`` for a route or router (BL-6.10)."""
    return [Depends(require_flag(flag))]
