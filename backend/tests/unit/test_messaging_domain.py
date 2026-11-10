"""Messaging rules (pure): emoji allow-list, direct keys, previews, edit window, send checks."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.messaging.domain import (
    DirectFacts,
    SendRestriction,
    can_edit,
    canonical_emoji,
    direct_key,
    direct_restriction,
    history_floor,
    should_notify,
    snippet,
)
from app.modules.messaging.schemas import SendMessageRequest

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


def test_emoji_allow_list_accepts_both_heart_forms() -> None:
    assert canonical_emoji("👍") == "👍"
    assert canonical_emoji("❤") == "❤️"
    assert canonical_emoji("❤️") == "❤️"
    assert canonical_emoji(" 🔥 ") == "🔥"
    for rejected in ("hello", "👍👍", "🍆", ""):
        assert canonical_emoji(rejected) is None


def test_direct_key_is_order_independent() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    assert direct_key(a, b) == direct_key(b, a)
    low, high = direct_key(a, b).split(":")
    assert low < high


def test_snippet_flattens_and_truncates() -> None:
    assert snippet(None) is None
    assert snippet("line one\n\n  line two") == "line one line two"
    long = snippet("x" * 500)
    assert long is not None
    assert len(long) == 140
    assert long.endswith("…")


@pytest.mark.req("DM-010")
def test_edit_window_is_fifteen_minutes() -> None:
    assert can_edit(created_at=NOW - timedelta(minutes=15), now=NOW)
    assert not can_edit(created_at=NOW - timedelta(minutes=15, seconds=1), now=NOW)


def test_history_floor_takes_the_later_boundary() -> None:
    assert history_floor(joined_at_seq=10, cleared_through_seq=4) == 10
    assert history_floor(joined_at_seq=0, cleared_through_seq=7) == 7


@pytest.mark.req("DM-001", "DM-012")
@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        (DirectFacts(True, False, False, True), None),
        (DirectFacts(True, True, False, False), SendRestriction.BLOCKED),
        # A block by the other person reads as a missing connection.
        (DirectFacts(True, False, True, False), SendRestriction.CONNECTION_REQUIRED),
        (DirectFacts(True, False, False, False), SendRestriction.CONNECTION_REQUIRED),
        (DirectFacts(False, False, False, True), SendRestriction.CONNECTION_REQUIRED),
    ],
)
def test_direct_send_restrictions(facts: DirectFacts, expected: SendRestriction | None) -> None:
    assert direct_restriction(facts) is expected


@pytest.mark.req("DM-009")
def test_notification_rules_follow_mute_and_level() -> None:
    assert should_notify(level="all", muted_until=None, now=NOW, mentioned=False)
    assert not should_notify(
        level="all", muted_until=NOW + timedelta(hours=1), now=NOW, mentioned=True
    )
    assert should_notify(
        level="all", muted_until=NOW - timedelta(hours=1), now=NOW, mentioned=False
    )
    assert not should_notify(level="none", muted_until=None, now=NOW, mentioned=True)
    assert should_notify(level="mentions", muted_until=None, now=NOW, mentioned=True)
    assert not should_notify(level="mentions", muted_until=None, now=NOW, mentioned=False)


@pytest.mark.parametrize(
    "body",
    [
        {"body": "  "},
        {},
        {"kind": "image", "body": "caption only"},
        {"body": "hi", "mentions": [str(uuid.UUID(int=1))] * 2},
        {"attachment_media_ids": [str(uuid.UUID(int=1))] * 2},
    ],
)
def test_send_request_validation(body: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        SendMessageRequest.model_validate({"client_message_id": str(uuid.uuid4()), **body})
