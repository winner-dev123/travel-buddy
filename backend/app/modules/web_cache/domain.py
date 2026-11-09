"""Pure rules: which outbox events purge which cached web pages, and the webhook signature.

Contract: ``webhooks.webCacheRevalidation`` (SAFE-012). Only visibility- and indexing-relevant
changes are pushed; ordinary edits (bio, display name) refresh through ISR (<= 60 s).
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# Receiver-side tag grammar is `profile:[a-z0-9_.]{3,30}`; anything else would be ignored there.
_PROFILE_VISIBILITY_FIELDS = frozenset({"handle", "account_visibility"})
_PRIVACY_VISIBILITY_FIELDS = frozenset({"profile_visibility", "show_trips_on_profile"})


@dataclass(frozen=True, slots=True)
class Revalidation:
    reason: str
    tags: tuple[str, ...]


def _profile_tag(handle: object) -> str | None:
    return f"profile:{handle}" if isinstance(handle, str) and handle else None


def _changed(data: Mapping[str, Any]) -> frozenset[str]:
    changed = data.get("changed")
    if not isinstance(changed, list):
        return frozenset()
    return frozenset(c for c in changed if isinstance(c, str))


def revalidation_for(event_type: str, data: Mapping[str, Any]) -> Revalidation | None:
    """The webhook to send for an outbox event, or ``None`` when no cached page is affected."""
    changed = _changed(data)
    tags: list[str] = []
    if event_type == "profile.updated":
        if not changed & _PROFILE_VISIBILITY_FIELDS:
            return None
        reason = "profile_visibility_changed"
        tags += [t for t in (_profile_tag(data.get("handle")),) if t]
        if "handle" in changed:  # the old URL must stop serving the profile
            tags += [t for t in (_profile_tag(data.get("previous_handle")),) if t]
    elif event_type == "privacy.updated":
        if changed & _PRIVACY_VISIBILITY_FIELDS:
            reason = "profile_visibility_changed"
        elif "search_engine_indexing" in changed:
            reason = "indexing_consent_changed"
        else:
            return None
        tags += [t for t in (_profile_tag(data.get("handle")),) if t]
    else:
        return None
    # The author's public stories change visibility/indexability with the account. Story pages
    # cannot be tagged by author (the tag is chosen before the data is fetched), so the whole
    # `stories` tag is purged: coarse but cheap at this scale. `profile:<handle>` stays for the
    # public profile pages to come.
    tags += ["stories", "sitemap"]
    return Revalidation(reason=reason, tags=tuple(dict.fromkeys(tags)))


def signature_header(secret: bytes, timestamp: int, body: bytes) -> str:
    """``X-TB-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256(secret, "<t>.<raw body>")>``."""
    digest = hmac.new(secret, f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"
