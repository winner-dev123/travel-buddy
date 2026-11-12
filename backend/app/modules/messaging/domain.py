"""Messaging rules (pure): ordering, edit window, emoji allow-list, gifts, previews and send
checks."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final


class ConversationKind(StrEnum):
    DIRECT = "direct"
    GROUP = "group"
    CHALLENGE_TEAM = "challenge_team"


class MessageKind(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    SYSTEM = "system"
    ANNOUNCEMENT = "announcement"
    GIFT = "gift"


class Gift(StrEnum):
    """The gift catalog (DM-016): free illustrated presents with no money value. The app ships
    the pictures; adding one is an app release plus a value here (no migration)."""

    COFFEE = "coffee"
    POSTCARD = "postcard"
    FLOWERS = "flowers"
    ICE_CREAM = "ice_cream"
    CAKE = "cake"
    BOARDING_PASS = "boarding_pass"  # noqa: S105 - a gift name, not a password
    SNOW_GLOBE = "snow_globe"
    COCONUT = "coconut"


class GiftEffect(StrEnum):
    """What plays on screen when a gift is opened (DM-016), chosen by the sender. The apps draw
    it; like the catalog, adding one is an app release plus a value here (no migration)."""

    PETALS = "petals"
    SPLASH = "splash"
    CONFETTI = "confetti"
    HEARTS = "hearts"


# Gifts sent without a choice (and those sent before effects existed) open with petals.
DEFAULT_GIFT_EFFECT = GiftEffect.PETALS


class ModerationState(StrEnum):
    VISIBLE = "visible"
    REMOVED_BY_MODERATOR = "removed_by_moderator"
    REMOVED_BY_ADMIN = "removed_by_admin"


class NotificationLevel(StrEnum):
    ALL = "all"
    MENTIONS = "mentions"
    NONE = "none"


class SendRestriction(StrEnum):
    CONNECTION_REQUIRED = "connection_required"
    BLOCKED = "blocked"
    MEMBER_RESTRICTED = "member_restricted"
    CHAT_ADMINS_ONLY = "chat_admins_only"
    ARCHIVED = "archived"


EDIT_WINDOW: Final = timedelta(minutes=15)  # DM-010
MAX_PINS: Final = 10  # GCHAT-006
SNIPPET_LENGTH: Final = 140
USER_CONTENT: Final = (MessageKind.TEXT, MessageKind.IMAGE, MessageKind.GIFT)
# A gift can be unsent (deleted) but not edited: there is no text to change.
EDITABLE: Final = (MessageKind.TEXT, MessageKind.IMAGE)

# Reactions are single emoji from a short allow-list (docs/04 §7: ≤ 16 bytes). The heart is
# accepted with or without the emoji variation selector and stored in one form.
_VS16 = "️"
ALLOWED_EMOJI: Final = frozenset(
    {
        "👍",
        "👎",
        "❤️",
        "😂",
        "😮",
        "😢",
        "😡",
        "🙏",
        "🔥",
        "🎉",
        "👏",
        "😍",
        "🤔",
        "🙌",
        "💯",
        "✅",
        "😊",
        "✈️",
        "🌍",
        "📍",
    }
)
_CANONICAL: Final = {e.replace(_VS16, ""): e for e in ALLOWED_EMOJI}


def canonical_emoji(value: str) -> str | None:
    """The stored form of an allowed reaction emoji, or None if it is not allowed."""
    return _CANONICAL.get(value.strip().replace(_VS16, ""))


def can_open_gift(
    *, kind: str, conversation_kind: str, sender_id: uuid.UUID | None, user_id: uuid.UUID
) -> bool:
    """Only the person a gift was sent to opens it: the other member of a direct chat."""
    return (
        kind == MessageKind.GIFT
        and conversation_kind == ConversationKind.DIRECT
        and sender_id is not None
        and sender_id != user_id
    )


def direct_key(a: uuid.UUID, b: uuid.UUID) -> str:
    """One direct conversation per pair: ``"{low}:{high}"``."""
    low, high = sorted((a, b), key=str)
    return f"{low}:{high}"


def snippet(body: str | None) -> str | None:
    if body is None:
        return None
    flat = " ".join(body.split())
    return flat if len(flat) <= SNIPPET_LENGTH else flat[: SNIPPET_LENGTH - 1] + "…"


def can_edit(*, created_at: datetime, now: datetime) -> bool:
    return now - created_at <= EDIT_WINDOW


def history_floor(*, joined_at_seq: int, cleared_through_seq: int) -> int:
    """Messages with ``seq`` above this are visible to the member (DM-011, group history)."""
    return max(joined_at_seq, cleared_through_seq)


@dataclass(frozen=True, slots=True)
class DirectFacts:
    """What decides whether a direct message may be sent (re-checked on every send)."""

    counterpart_active: bool
    blocked_by_me: bool
    blocked_me: bool
    connected: bool


def direct_restriction(facts: DirectFacts) -> SendRestriction | None:
    """Why a direct message can't be sent, if it can't. A block by the other person reads as a
    missing connection, so the block is not revealed."""
    if facts.blocked_by_me:
        return SendRestriction.BLOCKED
    if facts.blocked_me or not facts.counterpart_active or not facts.connected:
        return SendRestriction.CONNECTION_REQUIRED
    return None


def should_notify(
    *,
    level: str,
    muted_until: datetime | None,
    now: datetime,
    mentioned: bool,
) -> bool:
    """Whether a member hears about a new message (DM-009, GCHAT-005)."""
    if muted_until is not None and muted_until > now:
        return False
    if level == NotificationLevel.NONE:
        return False
    if level == NotificationLevel.MENTIONS:
        return mentioned
    return True
