"""Group premium status derived from the owner's grants (docs/07 section 5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.billing.entitlements import (
    EntitlementPolicy,
    Grant,
    GrantSource,
    GroupPremiumState,
    group_premium_status,
)

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)
GRACE = timedelta(days=14)

pytestmark = pytest.mark.req("GRP-009", "BILL-008")


def premium(starts: datetime, ends: datetime | None, revoked: datetime | None = None) -> Grant:
    return Grant(
        "premium", GrantSource.SUBSCRIPTION, starts_at=starts, ends_at=ends, revoked_at=revoked
    )


def test_active_owner_premium() -> None:
    status = group_premium_status([premium(NOW - 30 * DAY, NOW + DAY)], at=NOW)
    assert status.state is GroupPremiumState.ACTIVE
    assert status.premium_features_active
    assert status.grace_until is None


def test_natural_expiry_starts_admin_grace() -> None:
    ended = NOW - 3 * DAY
    status = group_premium_status([premium(NOW - 60 * DAY, ended)], at=NOW)
    assert status.state is GroupPremiumState.GRACE
    assert status.premium_features_active
    assert status.grace_until == ended + GRACE


def test_grace_boundary_is_exclusive() -> None:
    ended = NOW - GRACE
    status = group_premium_status([premium(NOW - 60 * DAY, ended)], at=NOW)
    assert status.state is GroupPremiumState.LAPSED
    assert not status.premium_features_active


def test_refund_revocation_skips_grace() -> None:
    grant = premium(NOW - 10 * DAY, NOW + 20 * DAY, revoked=NOW - DAY)
    status = group_premium_status([grant], at=NOW)
    assert status.state is GroupPremiumState.LAPSED


def test_owner_never_premium_is_lapsed() -> None:
    status = group_premium_status([], at=NOW)
    assert status.state is GroupPremiumState.LAPSED


def test_future_grant_does_not_count() -> None:
    status = group_premium_status([premium(NOW + DAY, NOW + 30 * DAY)], at=NOW)
    assert status.state is GroupPremiumState.LAPSED


def test_resubscribe_after_lapse_restores_active() -> None:
    old = premium(NOW - 90 * DAY, NOW - 60 * DAY)
    new = premium(NOW - DAY, NOW + 29 * DAY)
    assert group_premium_status([old, new], at=NOW).state is GroupPremiumState.ACTIVE


def test_latest_ending_grant_decides_grace() -> None:
    refunded_earlier = premium(NOW - 40 * DAY, NOW - 5 * DAY, revoked=NOW - 20 * DAY)
    expired_later = premium(NOW - 35 * DAY, NOW - 2 * DAY)
    status = group_premium_status([refunded_earlier, expired_later], at=NOW)
    assert status.state is GroupPremiumState.GRACE
    assert status.grace_until == NOW - 2 * DAY + GRACE


def test_tie_between_revocation_and_expiry_is_conservative() -> None:
    end = NOW - DAY
    revoked = premium(NOW - 30 * DAY, NOW + 30 * DAY, revoked=end)
    expired = premium(NOW - 30 * DAY, end)
    assert group_premium_status([expired, revoked], at=NOW).state is GroupPremiumState.LAPSED


def test_grace_period_is_configurable() -> None:
    policy = EntitlementPolicy(group_admin_grace_period=timedelta(days=2))
    status = group_premium_status([premium(NOW - 60 * DAY, NOW - 3 * DAY)], at=NOW, policy=policy)
    assert status.state is GroupPremiumState.LAPSED


def test_content_grants_do_not_make_group_premium() -> None:
    guide = Grant("content:guide:rio", GrantSource.PURCHASE, starts_at=NOW - DAY)
    assert group_premium_status([guide], at=NOW).state is GroupPremiumState.LAPSED
