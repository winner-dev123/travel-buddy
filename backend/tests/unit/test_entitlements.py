"""Entitlement evaluator (docs/07 sections 3-4, ADR-0006)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.modules.billing.entitlements import (
    DEFAULT_POLICY,
    EntitlementPolicy,
    Feature,
    Grant,
    GrantSource,
    Plan,
    Quota,
    QuotaRule,
    evaluate,
    start_of_next_month,
)

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
DAY = timedelta(days=1)


def premium(
    starts: datetime = NOW - 10 * DAY,
    ends: datetime | None = NOW + 20 * DAY,
    revoked: datetime | None = None,
    source: GrantSource = GrantSource.SUBSCRIPTION,
) -> Grant:
    return Grant("premium", source, starts_at=starts, ends_at=ends, revoked_at=revoked)


pytestmark = pytest.mark.req("BILL-007")


def test_no_grants_is_free_with_no_features() -> None:
    snapshot = evaluate([], at=NOW)
    assert snapshot.plan is Plan.FREE
    assert snapshot.features == frozenset()
    assert not snapshot.has(Feature.GROUPS_CREATE)
    assert snapshot.premium_until is None


@pytest.mark.req("GRP-001")
def test_active_premium_grants_all_premium_features() -> None:
    snapshot = evaluate([premium()], at=NOW)
    assert snapshot.plan is Plan.PREMIUM
    assert all(snapshot.has(feature) for feature in Feature)
    assert snapshot.premium_until == NOW + 20 * DAY


@pytest.mark.req("BILL-005")
@pytest.mark.parametrize(
    ("at", "active"),
    [
        (NOW - 10 * DAY - timedelta(seconds=1), False),  # before start
        (NOW - 10 * DAY, True),  # start is inclusive
        (NOW + 20 * DAY - timedelta(seconds=1), True),
        (NOW + 20 * DAY, False),  # end is exclusive
    ],
)
def test_grant_window_boundaries(at: datetime, active: bool) -> None:
    assert (evaluate([premium()], at=at).plan is Plan.PREMIUM) is active


@pytest.mark.req("BILL-005")
def test_revocation_ends_access_immediately() -> None:
    grant = premium(revoked=NOW - timedelta(minutes=1))
    assert evaluate([grant], at=NOW).plan is Plan.FREE
    # Before the revocation instant the grant was active (useful for audits).
    assert evaluate([grant], at=NOW - timedelta(minutes=2)).plan is Plan.PREMIUM


def test_union_across_providers_uses_latest_end() -> None:
    store = premium(ends=NOW + 5 * DAY)
    web = premium(ends=NOW + 40 * DAY)
    snapshot = evaluate([store, web], at=NOW)
    assert snapshot.plan is Plan.PREMIUM
    assert snapshot.premium_until == NOW + 40 * DAY


def test_open_ended_grant_has_no_premium_until() -> None:
    lifetime = premium(ends=None, source=GrantSource.ADMIN_GRANT)
    snapshot = evaluate([lifetime, premium()], at=NOW)
    assert snapshot.plan is Plan.PREMIUM
    assert snapshot.premium_until is None


@pytest.mark.req("GUIDE-004")
def test_content_purchases_grant_specific_items_without_premium() -> None:
    guide = Grant("content:guide:rio", GrantSource.PURCHASE, starts_at=NOW - DAY)
    snapshot = evaluate([guide], at=NOW)
    assert snapshot.plan is Plan.FREE
    assert snapshot.has_content("content:guide:rio")
    assert not snapshot.has_content("content:guide:lisbon")
    assert not snapshot.has(Feature.GUIDES_PREMIUM)


def test_unknown_entitlement_keys_grant_nothing() -> None:
    snapshot = evaluate([Grant("platinum", GrantSource.PROMO, starts_at=NOW - DAY)], at=NOW)
    assert snapshot.plan is Plan.FREE
    assert snapshot.features == frozenset()


@pytest.mark.req("AI-009", "OFF-004")
@pytest.mark.parametrize(
    ("quota", "free_limit", "premium_limit"),
    [
        (Quota.AI_ITINERARY_GENERATIONS, 5, 60),
        (Quota.AI_TRIP_REPLANS, 0, 60),
        (Quota.OFFLINE_PACKAGES, 1, 15),
        (Quota.GROUPS_OWNED, 0, 10),
    ],
)
def test_default_quota_limits(quota: Quota, free_limit: int, premium_limit: int) -> None:
    assert evaluate([], at=NOW).quota(quota, used=0).limit == free_limit
    assert evaluate([premium()], at=NOW).quota(quota, used=0).limit == premium_limit


@pytest.mark.req("AI-009")
def test_monthly_quota_resets_at_next_utc_month() -> None:
    status = evaluate([], at=NOW).quota(Quota.AI_ITINERARY_GENERATIONS, used=5)
    assert status.exhausted
    assert status.remaining == 0
    assert status.resets_at == datetime(2026, 12, 1, tzinfo=UTC)


def test_concurrent_quota_has_no_reset() -> None:
    status = evaluate([premium()], at=NOW).quota(Quota.OFFLINE_PACKAGES, used=3)
    assert status.resets_at is None
    assert status.remaining == 12


def test_can_consume() -> None:
    snapshot = evaluate([], at=NOW)
    assert snapshot.can_consume(Quota.AI_ITINERARY_GENERATIONS, used=4)
    assert not snapshot.can_consume(Quota.AI_ITINERARY_GENERATIONS, used=5)
    assert not snapshot.can_consume(Quota.AI_ITINERARY_GENERATIONS, used=4, amount=2)
    assert not snapshot.can_consume(Quota.GROUPS_OWNED, used=0)


def test_start_of_next_month_handles_december() -> None:
    assert start_of_next_month(datetime(2026, 12, 31, 23, 59, tzinfo=UTC)) == datetime(
        2027, 1, 1, tzinfo=UTC
    )


def test_policy_is_configurable() -> None:
    policy = EntitlementPolicy(
        free_features=frozenset({Feature.GUIDES_PREMIUM}),
        quotas={
            **DEFAULT_POLICY.quotas,
            Quota.AI_ITINERARY_GENERATIONS: QuotaRule(
                10, 100, DEFAULT_POLICY.quotas[Quota.AI_ITINERARY_GENERATIONS].period
            ),
        },
    )
    snapshot = evaluate([], at=NOW, policy=policy)
    assert snapshot.has(Feature.GUIDES_PREMIUM)
    assert snapshot.quota(Quota.AI_ITINERARY_GENERATIONS, used=0).limit == 10


def test_policy_validation() -> None:
    with pytest.raises(ValueError, match="missing quota"):
        EntitlementPolicy(quotas={})
    with pytest.raises(ValueError, match="subset"):
        EntitlementPolicy(
            free_features=frozenset({Feature.GROUPS_CREATE}),
            premium_features=frozenset(),
        )


def test_naive_datetimes_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Grant("premium", GrantSource.PROMO, starts_at=datetime(2026, 1, 1))  # noqa: DTZ001
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate([], at=datetime(2026, 1, 1))  # noqa: DTZ001


def test_grant_end_must_follow_start() -> None:
    with pytest.raises(ValueError, match="after starts_at"):
        premium(starts=NOW, ends=NOW)


@pytest.mark.req("BILL-007", "ADM-005")
def test_runtime_overrides_apply_over_the_defaults() -> None:
    from app.modules.billing.entitlements import (
        DEFAULT_POLICY,
        Grant,
        GrantSource,
        GroupPremiumState,
        Quota,
        group_premium_status,
    )
    from app.modules.billing.models import EntitlementPolicyOverride
    from app.modules.billing.service import _policy_from

    assert _policy_from(None) is DEFAULT_POLICY
    row = EntitlementPolicyOverride(
        id=1,
        quotas={
            "ai.trip_replans": {"free": 2, "premium": 90},
            "retired.quota": {"free": 1, "premium": 1},  # from a newer deploy: ignored
            "offline.packages": {"free": "x"},  # malformed: the default stays
        },
        group_admin_grace_days=30,
        version=3,
    )
    policy = _policy_from(row)
    assert (
        policy.quotas[Quota.AI_TRIP_REPLANS].free,
        policy.quotas[Quota.AI_TRIP_REPLANS].premium,
    ) == (2, 90)
    assert policy.quotas[Quota.OFFLINE_PACKAGES] == DEFAULT_POLICY.quotas[Quota.OFFLINE_PACKAGES]
    assert (
        policy.quotas[Quota.AI_TRIP_REPLANS].period
        == DEFAULT_POLICY.quotas[Quota.AI_TRIP_REPLANS].period
    )

    # The longer grace keeps a lapsed owner's group premium features for 30 days, not 14.
    ended = datetime(2026, 11, 1, tzinfo=UTC)
    grant = Grant(
        entitlement_key="premium",
        source_type=GrantSource.SUBSCRIPTION,
        starts_at=ended - timedelta(days=30),
        ends_at=ended,
    )
    at = ended + timedelta(days=20)
    assert group_premium_status([grant], at=at).state is GroupPremiumState.LAPSED
    assert group_premium_status([grant], at=at, policy=policy).state is not GroupPremiumState.LAPSED
