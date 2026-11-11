"""Pure entitlement evaluator: the single source of feature gating (ADR-0006, docs/07).

No I/O lives here. Persistence (``subscription_entitlements``) and provider adapters (Apple,
Google, Stripe, dev) normalize into :class:`Grant` objects; this module decides what they allow.
Other modules must go through ``billing.service`` (Phase 3), which wraps these functions with
data loading and caching, and must never read subscription tables directly.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from app.core.time import require_aware

PREMIUM_ENTITLEMENT = "premium"
CONTENT_ENTITLEMENT_PREFIX = "content:"


class Feature(StrEnum):
    GROUPS_CREATE = "groups.create"
    CHALLENGES_CREATE = "challenges.create"
    GUIDES_PREMIUM = "guides.premium"
    AUDIO_TOURS_PREMIUM = "audio_tours.premium"
    AI_TRIP_REPLAN = "ai.trip_replan"


class Quota(StrEnum):
    AI_ITINERARY_GENERATIONS = "ai.itinerary_generations"
    AI_TRIP_REPLANS = "ai.trip_replans"
    OFFLINE_PACKAGES = "offline.packages"
    GROUPS_OWNED = "groups.owned"


class QuotaPeriod(StrEnum):
    MONTHLY = "monthly"  # calendar month, UTC
    NONE = "none"  # concurrent limit (e.g. active offline licenses)


class Plan(StrEnum):
    FREE = "free"
    PREMIUM = "premium"


class GrantSource(StrEnum):
    SUBSCRIPTION = "subscription"
    PURCHASE = "purchase"
    PROMO = "promo"
    ADMIN_GRANT = "admin_grant"


@dataclass(frozen=True, slots=True)
class Grant:
    """A materialized entitlement grant (one row of ``subscription_entitlements``)."""

    entitlement_key: str
    source_type: GrantSource
    starts_at: datetime
    ends_at: datetime | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        require_aware(self.starts_at, "starts_at")
        if self.ends_at is not None:
            require_aware(self.ends_at, "ends_at")
            if self.ends_at <= self.starts_at:
                raise ValueError("ends_at must be after starts_at")
        if self.revoked_at is not None:
            require_aware(self.revoked_at, "revoked_at")

    @property
    def effective_end(self) -> datetime | None:
        """When the grant stops being active (earliest of natural end and revocation)."""
        candidates = [t for t in (self.ends_at, self.revoked_at) if t is not None]
        return min(candidates) if candidates else None

    @property
    def ended_by_revocation(self) -> bool:
        """True when a refund/revocation cut the grant short (no admin grace applies)."""
        return self.revoked_at is not None and (
            self.ends_at is None or self.revoked_at < self.ends_at
        )

    def is_active_at(self, at: datetime) -> bool:
        require_aware(at, "at")
        if at < self.starts_at:
            return False
        end = self.effective_end
        return end is None or at < end


@dataclass(frozen=True, slots=True)
class QuotaRule:
    free: int
    premium: int
    period: QuotaPeriod

    def __post_init__(self) -> None:
        if self.free < 0 or self.premium < 0:
            raise ValueError("quota limits must be non-negative")

    def limit_for(self, plan: Plan) -> int:
        return self.premium if plan is Plan.PREMIUM else self.free


DEFAULT_QUOTAS: Mapping[Quota, QuotaRule] = {
    Quota.AI_ITINERARY_GENERATIONS: QuotaRule(free=5, premium=60, period=QuotaPeriod.MONTHLY),
    Quota.AI_TRIP_REPLANS: QuotaRule(free=0, premium=60, period=QuotaPeriod.MONTHLY),
    Quota.OFFLINE_PACKAGES: QuotaRule(free=1, premium=15, period=QuotaPeriod.NONE),
    Quota.GROUPS_OWNED: QuotaRule(free=0, premium=10, period=QuotaPeriod.NONE),
}


@dataclass(frozen=True, slots=True)
class EntitlementPolicy:
    """Configurable policy values (docs/07 section 3). Loaded from settings in Phase 3."""

    free_features: frozenset[Feature] = frozenset()
    premium_features: frozenset[Feature] = frozenset(Feature)
    quotas: Mapping[Quota, QuotaRule] = field(default_factory=lambda: dict(DEFAULT_QUOTAS))
    group_admin_grace_period: timedelta = timedelta(days=14)

    def __post_init__(self) -> None:
        missing = set(Quota) - set(self.quotas)
        if missing:
            raise ValueError(f"policy missing quota rules: {sorted(q.value for q in missing)}")
        if not self.free_features <= self.premium_features:
            raise ValueError("free features must be a subset of premium features")
        if self.group_admin_grace_period < timedelta(0):
            raise ValueError("grace period must be non-negative")


DEFAULT_POLICY = EntitlementPolicy()


def start_of_next_month(at: datetime) -> datetime:
    at = require_aware(at, "at").astimezone(UTC)
    if at.month == 12:
        return datetime(at.year + 1, 1, 1, tzinfo=UTC)
    return datetime(at.year, at.month + 1, 1, tzinfo=UTC)


def start_of_month(at: datetime) -> datetime:
    at = require_aware(at, "at").astimezone(UTC)
    return datetime(at.year, at.month, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class QuotaStatus:
    quota: Quota
    limit: int
    used: int
    resets_at: datetime | None

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    @property
    def exhausted(self) -> bool:
        return self.used >= self.limit


@dataclass(frozen=True, slots=True)
class EntitlementSnapshot:
    evaluated_at: datetime
    plan: Plan
    premium_until: datetime | None
    features: frozenset[Feature]
    content_keys: frozenset[str]
    policy: EntitlementPolicy

    def has(self, feature: Feature) -> bool:
        return feature in self.features

    def has_content(self, content_key: str) -> bool:
        """Access to a specific purchased item, e.g. ``content:guide:<uuid>``."""
        return content_key in self.content_keys

    def quota(self, quota: Quota, *, used: int) -> QuotaStatus:
        if used < 0:
            raise ValueError("used must be non-negative")
        rule = self.policy.quotas[quota]
        resets_at = (
            start_of_next_month(self.evaluated_at) if rule.period is QuotaPeriod.MONTHLY else None
        )
        return QuotaStatus(
            quota=quota, limit=rule.limit_for(self.plan), used=used, resets_at=resets_at
        )

    def can_consume(self, quota: Quota, *, used: int, amount: int = 1) -> bool:
        if amount < 1:
            raise ValueError("amount must be >= 1")
        status = self.quota(quota, used=used)
        return status.used + amount <= status.limit


def _chain_end(grants: Sequence[Grant], end: datetime) -> datetime | None:
    """Follow grants that start by the time the current one ends (a stacked pass, a renewal
    already paid), so "Premium until" is the end of the unbroken run, not of the first piece."""
    while True:
        following = [
            g
            for g in grants
            if g.starts_at <= end
            and (g.effective_end is None or g.effective_end > end)
            and g.is_active_at(g.starts_at)
        ]
        if not following:
            return end
        if any(g.effective_end is None for g in following):
            return None
        end = max(g.effective_end for g in following if g.effective_end is not None)


def evaluate(
    grants: Iterable[Grant], *, at: datetime, policy: EntitlementPolicy = DEFAULT_POLICY
) -> EntitlementSnapshot:
    """Evaluate the union of a user's grants at instant ``at``.

    Grants from every provider (Apple, Google, Stripe, promotions) are combined; any active
    ``premium`` grant yields the premium plan.
    """
    require_aware(at, "at")
    grants = list(grants)
    active = [g for g in grants if g.is_active_at(at)]
    premium = [g for g in active if g.entitlement_key == PREMIUM_ENTITLEMENT]
    plan = Plan.PREMIUM if premium else Plan.FREE

    premium_until: datetime | None = None
    if premium:
        ends = [g.effective_end for g in premium]
        # An open-ended grant (e.g. lifetime promo) means there is no end date to show.
        premium_until = None if any(e is None for e in ends) else max(e for e in ends if e)
        if premium_until is not None:
            premium_until = _chain_end(
                [g for g in grants if g.entitlement_key == PREMIUM_ENTITLEMENT], premium_until
            )

    return EntitlementSnapshot(
        evaluated_at=at,
        plan=plan,
        premium_until=premium_until,
        features=policy.premium_features if plan is Plan.PREMIUM else policy.free_features,
        content_keys=frozenset(
            g.entitlement_key
            for g in active
            if g.entitlement_key.startswith(CONTENT_ENTITLEMENT_PREFIX)
        ),
        policy=policy,
    )


class GroupPremiumState(StrEnum):
    ACTIVE = "active"  # owner holds premium
    GRACE = "grace"  # owner's premium ended naturally; admin grace period running
    LAPSED = "lapsed"  # grace over, never premium, or ended by refund/revocation


@dataclass(frozen=True, slots=True)
class GroupPremiumStatus:
    state: GroupPremiumState
    grace_until: datetime | None = None

    @property
    def premium_features_active(self) -> bool:
        return self.state is not GroupPremiumState.LAPSED


def group_premium_status(
    owner_grants: Iterable[Grant], *, at: datetime, policy: EntitlementPolicy = DEFAULT_POLICY
) -> GroupPremiumStatus:
    """Premium status of a group, derived from its owner's grants (docs/07 section 5).

    Safety moderation capabilities never depend on this value. Callers in the groups module
    must only use it for the premium-gated actions listed in the policy table.
    """
    require_aware(at, "at")
    premium = [g for g in owner_grants if g.entitlement_key == PREMIUM_ENTITLEMENT]
    if any(g.is_active_at(at) for g in premium):
        return GroupPremiumStatus(GroupPremiumState.ACTIVE)

    ended: list[tuple[datetime, Grant]] = []
    for grant in premium:
        end = grant.effective_end
        if end is not None and grant.starts_at <= at and end <= at:
            ended.append((end, grant))
    if not ended:
        return GroupPremiumStatus(GroupPremiumState.LAPSED)

    # Latest end wins; on a tie, a revocation wins (the conservative outcome).
    latest_end, latest = max(ended, key=lambda item: (item[0], item[1].ended_by_revocation))
    if latest.ended_by_revocation:
        return GroupPremiumStatus(GroupPremiumState.LAPSED)
    grace_until = latest_end + policy.group_admin_grace_period
    if at < grace_until:
        return GroupPremiumStatus(GroupPremiumState.GRACE, grace_until=grace_until)
    return GroupPremiumStatus(GroupPremiumState.LAPSED)
