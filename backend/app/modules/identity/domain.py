"""Pure identity rules: age gate, refresh-token rotation decisions, device names.

No I/O here (enforced by tests/unit/test_architecture_boundaries.py).

Refresh tokens (ADR-0003, ADR-0011):
* A session is one token family. Only SHA-256 hashes are stored.
* Each successor is ``HMAC-SHA256(derivation_key, previous_raw_token)``. Because the successor is a
  pure function of the previous token, the server can return the *same* successor when the
  immediately previous token is replayed within the reuse leeway, without storing raw tokens.
* Any other reuse (previous token after the leeway, or any older retired token) is treated as
  theft and revokes the whole family.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum

# ───────────────────────────── Age gate (AUTH-008) ─────────────────────────────


def age_on(birth_date: date, today: date) -> int:
    if birth_date > today:
        raise ValueError("birth_date is in the future")
    years = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        years -= 1
    return years


def is_age_eligible(birth_date: date, today: date, minimum_age: int) -> bool:
    return age_on(birth_date, today) >= minimum_age


# ─────────────────────────── Refresh token rotation ───────────────────────────


class RefreshMatch(StrEnum):
    CURRENT = "current"  # presented token is the session's current refresh token
    PREVIOUS = "previous"  # presented token is the immediately previous one
    RETIRED = "retired"  # presented token is an older ancestor
    NONE = "none"  # unknown token


class RefreshOutcome(StrEnum):
    ROTATE = "rotate"
    REPLAY_SUCCESSOR = "replay_successor"
    REUSE_DETECTED = "reuse_detected"
    INVALID = "invalid"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class SessionTokenState:
    revoked: bool
    expires_at: datetime
    rotated_at: datetime | None


def decide_refresh(
    match: RefreshMatch,
    state: SessionTokenState | None,
    *,
    now: datetime,
    leeway: timedelta,
) -> RefreshOutcome:
    if match is RefreshMatch.NONE or state is None:
        return RefreshOutcome.INVALID
    if state.revoked:
        return RefreshOutcome.REVOKED
    if match is RefreshMatch.RETIRED:
        return RefreshOutcome.REUSE_DETECTED
    if match is RefreshMatch.PREVIOUS:
        within_leeway = state.rotated_at is not None and now - state.rotated_at <= leeway
        return RefreshOutcome.REPLAY_SUCCESSOR if within_leeway else RefreshOutcome.REUSE_DETECTED
    if now >= state.expires_at:
        return RefreshOutcome.EXPIRED
    return RefreshOutcome.ROTATE


def hash_token(raw: str) -> bytes:
    return hashlib.sha256(raw.encode("utf-8")).digest()


def derive_successor_token(raw: str, derivation_key: bytes) -> str:
    digest = hmac.new(derivation_key, raw.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# ───────────────────────────── Session device names ─────────────────────────────

_BROWSERS = (
    ("Edg/", "Edge"),
    ("OPR/", "Opera"),
    ("Firefox/", "Firefox"),
    ("Chrome/", "Chrome"),
    ("Safari/", "Safari"),
)
_SYSTEMS = (
    ("iPhone", "iOS"),
    ("iPad", "iPadOS"),
    ("Android", "Android"),
    ("Mac OS X", "macOS"),
    ("Windows", "Windows"),
    ("CrOS", "ChromeOS"),
    ("Linux", "Linux"),
)


def device_name_from_user_agent(user_agent: str | None) -> str | None:
    """Human label such as "Chrome on macOS" for session lists (DeviceInfo omitted by web)."""
    if not user_agent:
        return None
    browser = next((label for marker, label in _BROWSERS if marker in user_agent), None)
    system = next((label for marker, label in _SYSTEMS if marker in user_agent), None)
    if browser and system:
        return f"{browser} on {system}"
    return browser or system
