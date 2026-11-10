"""Subscription lifecycle (pure; docs/07 §4)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.billing.domain import (
    StoreEvent,
    SubscriptionStatus,
    grant_window,
    management,
    next_status,
)
from app.modules.billing.entitlements import Grant, GrantSource

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
START = NOW - timedelta(days=10)
END = NOW + timedelta(days=20)
S = SubscriptionStatus


@pytest.mark.req("BILL-008")
@pytest.mark.parametrize(
    ("current", "event", "expected"),
    [
        (S.ACTIVE, StoreEvent.GRACE, S.IN_GRACE_PERIOD),
        (S.IN_GRACE_PERIOD, StoreEvent.RECOVERED, S.ACTIVE),
        (S.IN_GRACE_PERIOD, StoreEvent.BILLING_RETRY, S.IN_BILLING_RETRY),
        (S.IN_BILLING_RETRY, StoreEvent.EXPIRED, S.EXPIRED),
        (S.ACTIVE, StoreEvent.PAUSED, S.PAUSED),
        (S.PAUSED, StoreEvent.RESUMED, S.ACTIVE),
        (S.EXPIRED, StoreEvent.RENEWED, S.ACTIVE),
        (S.REVOKED, StoreEvent.RENEWED, S.ACTIVE),
        (S.ACTIVE, StoreEvent.REFUNDED, S.REVOKED),
        (S.ACTIVE, StoreEvent.AUTO_RENEW_OFF, S.ACTIVE),
        (S.EXPIRED, StoreEvent.GRACE, None),
        (S.REVOKED, StoreEvent.REFUNDED, None),
    ],
)
def test_transitions(current: S, event: StoreEvent, expected: S | None) -> None:
    assert next_status(current, event) is expected


@pytest.mark.req("BILL-005")
def test_grant_window_per_state() -> None:
    def active_now(status: S, grace: datetime | None = None) -> bool:
        window = grant_window(
            status, starts_at=START, current_period_end=END, grace_period_ends_at=grace, now=NOW
        )
        grant = Grant(
            entitlement_key="premium",
            source_type=GrantSource.SUBSCRIPTION,
            starts_at=START,
            ends_at=window.ends_at,
            revoked_at=window.revoked_at,
        )
        return grant.is_active_at(NOW)

    assert active_now(S.ACTIVE)
    assert active_now(S.IN_GRACE_PERIOD, grace=NOW + timedelta(days=5))
    for ended in (S.IN_BILLING_RETRY, S.PAUSED, S.EXPIRED, S.REVOKED):
        assert not active_now(ended)
    revoked = grant_window(
        S.REVOKED, starts_at=START, current_period_end=END, grace_period_ends_at=None, now=NOW
    )
    assert revoked.revoked_at == NOW  # refunds end premium immediately, without grace


def test_management_path_per_provider() -> None:
    assert management("apple") == "app_store"
    assert management("google") == "google_play"
    assert management("stripe") == "stripe_portal"
