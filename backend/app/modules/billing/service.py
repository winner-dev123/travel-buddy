"""Public interface of the billing module: the only entitlement gate (ADR-0006).

Phase 1 status: subscription tables and store/Stripe adapters arrive in Phase 3 (BL-3.01/3.02).
Until then no user can hold a grant, so every user evaluates to the free plan, which is exactly
what the evaluator returns for an empty grant list. Quota usage is zero because the features that
consume quotas (AI, offline packs, groups) do not exist yet. Nothing here is simulated.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.billing.entitlements import (
    DEFAULT_POLICY,
    EntitlementPolicy,
    EntitlementSnapshot,
    Feature,
    Grant,
    Plan,
    Quota,
    evaluate,
)
from app.modules.billing.schemas import (
    EntitlementFeatures,
    EntitlementQuotas,
    Entitlements,
    QuotaStatusOut,
)


async def _load_grants(session: AsyncSession, user_id: uuid.UUID) -> list[Grant]:
    # subscription_entitlements is introduced in Phase 3; no grants can exist before then.
    return []


async def snapshot(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    at: datetime,
    policy: EntitlementPolicy = DEFAULT_POLICY,
) -> EntitlementSnapshot:
    return evaluate(await _load_grants(session, user_id), at=at, policy=policy)


async def has(session: AsyncSession, user_id: uuid.UUID, feature: Feature, *, at: datetime) -> bool:
    return (await snapshot(session, user_id, at=at)).has(feature)


def _quota(snap: EntitlementSnapshot, quota: Quota, used: int) -> QuotaStatusOut:
    status = snap.quota(quota, used=used)
    return QuotaStatusOut(limit=status.limit, used=status.used, resets_at=status.resets_at)


async def get_entitlements(
    session: AsyncSession, user_id: uuid.UUID, *, at: datetime
) -> Entitlements:
    snap = await snapshot(session, user_id, at=at)
    return Entitlements(
        plan="premium" if snap.plan is Plan.PREMIUM else "free",
        status="active" if snap.plan is Plan.PREMIUM else "none",
        premium_until=snap.premium_until,
        store_grace_until=None,
        features=EntitlementFeatures.model_validate(
            {feature.value: snap.has(feature) for feature in Feature}
        ),
        quotas=EntitlementQuotas.model_validate(
            {quota.value: _quota(snap, quota, used=0) for quota in Quota}
        ),
        active_subscription=None,
    )
