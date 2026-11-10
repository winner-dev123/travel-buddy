"""Public interface of the billing module: the only entitlement gate (ADR-0006, docs/07).

- ``snapshot``/``has``/``get_entitlements`` evaluate the user's materialized grants
  (``subscription_entitlements``) at an instant; nothing else in the system reads billing tables.
- ``BillingService`` verifies store purchases through a provider (never trusting the client),
  binds each store transaction to one account (``409 purchase_already_linked`` otherwise), and
  rewrites the grant whenever a subscription changes state, in the same transaction.
- Store notifications are normalized into :class:`StoreEvent` and applied once per provider event,
  ignoring events older than the subscription's last one (docs/07 §4).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode
from app.core.security.principal import Principal
from app.core.time import Clock
from app.modules.billing.domain import (
    GRACE,
    PERIODS,
    ProductKind,
    StoreEvent,
    SubscriptionStatus,
    grant_window,
    management,
    next_status,
)
from app.modules.billing.entitlements import (
    DEFAULT_POLICY,
    EntitlementPolicy,
    EntitlementSnapshot,
    Feature,
    Grant,
    GrantSource,
    GroupPremiumStatus,
    Plan,
    Quota,
    evaluate,
    group_premium_status,
)
from app.modules.billing.models import (
    BillingEvent,
    Product,
    Purchase,
    Subscription,
    SubscriptionEntitlement,
)
from app.modules.billing.providers import BillingProvider, PurchaseClaim, StoreTransaction
from app.modules.billing.schemas import (
    ActiveSubscription,
    EntitlementFeatures,
    EntitlementQuotas,
    Entitlements,
    ProductOut,
    PurchaseOut,
    QuotaStatusOut,
    VerifyPurchaseResult,
)
from app.modules.platform import service as platform

VERIFY_ROUTE = "POST /v1/billing/purchases/verify"
RESTORE_ROUTE = "POST /v1/billing/purchases/restore"
_PREMIUM_STATES = (SubscriptionStatus.ACTIVE, SubscriptionStatus.IN_GRACE_PERIOD)
_PROVIDER_FOR_PLATFORM = {"ios": "apple", "android": "google", "web": "stripe"}


async def _load_grants(session: AsyncSession, user_id: uuid.UUID) -> list[Grant]:
    rows = await session.scalars(
        select(SubscriptionEntitlement).where(SubscriptionEntitlement.user_id == user_id)
    )
    return [
        Grant(
            entitlement_key=row.entitlement_key,
            source_type=GrantSource(row.source_type),
            starts_at=row.starts_at,
            ends_at=row.ends_at,
            revoked_at=row.revoked_at,
        )
        for row in rows
    ]


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


async def group_premium(
    session: AsyncSession, owner_id: uuid.UUID, *, at: datetime
) -> GroupPremiumStatus:
    """A group's premium status from its owner's grants, with the admin grace (docs/07 §5)."""
    return group_premium_status(await _load_grants(session, owner_id), at=at)


async def quota_limit(
    session: AsyncSession, user_id: uuid.UUID, quota: Quota, *, at: datetime
) -> int:
    return (await snapshot(session, user_id, at=at)).quota(quota, used=0).limit


def _quota(snap: EntitlementSnapshot, quota: Quota, used: int) -> QuotaStatusOut:
    status = snap.quota(quota, used=used)
    return QuotaStatusOut(limit=status.limit, used=status.used, resets_at=status.resets_at)


async def get_entitlements(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    at: datetime,
    usage: Mapping[Quota, int] | None = None,
) -> Entitlements:
    snap = await snapshot(session, user_id, at=at)
    latest = await session.scalar(
        select(Subscription)
        .where(Subscription.user_id == user_id)
        .order_by(Subscription.updated_at.desc())
        .limit(1)
    )
    granting = None
    if snap.plan is Plan.PREMIUM:
        granting = await session.scalar(
            select(Subscription)
            .where(Subscription.user_id == user_id, Subscription.status.in_(_PREMIUM_STATES))
            .order_by(Subscription.current_period_end.desc().nulls_first())
            .limit(1)
        )
    if granting is not None:
        status = granting.status
    elif snap.plan is Plan.PREMIUM:
        status = "active"  # a promotion or admin grant
    else:
        status = latest.status if latest is not None else "none"
        if status in _PREMIUM_STATES:
            status = "expired"  # the grant ran out before the store said so
    counts = dict(usage or {})
    return Entitlements(
        plan="premium" if snap.plan is Plan.PREMIUM else "free",
        status=status,  # type: ignore[arg-type]
        premium_until=snap.premium_until,
        store_grace_until=(
            granting.grace_period_ends_at
            if granting is not None and granting.status == SubscriptionStatus.IN_GRACE_PERIOD
            else None
        ),
        features=EntitlementFeatures.model_validate(
            {feature.value: snap.has(feature) for feature in Feature}
        ),
        quotas=EntitlementQuotas.model_validate(
            {quota.value: _quota(snap, quota, used=counts.get(quota, 0)) for quota in Quota}
        ),
        active_subscription=(
            ActiveSubscription(
                provider=granting.provider,  # type: ignore[arg-type]
                product_id=granting.product_id,
                auto_renew=granting.auto_renew_enabled,
                management=management(granting.provider),  # type: ignore[arg-type]
            )
            if granting is not None
            else None
        ),
    )


def _product_out(row: Product) -> ProductOut:
    return ProductOut.model_validate(
        {
            "id": row.id,
            "sku": row.sku,
            "platform": row.platform,
            "provider": _PROVIDER_FOR_PLATFORM[row.platform],
            "kind": row.kind,
            "plan_key": row.plan_key,
            "period": row.period,
            "entitlement_keys": list(row.entitlement_keys),
            "grants_content": row.grants_content or [],
        }
    )


async def _materialize(
    session: AsyncSession, subscription: Subscription, product: Product, *, now: datetime
) -> None:
    """Rewrite the subscription's grants for its current state (docs/07 §4)."""
    starts_at = subscription.created_at or subscription.current_period_start
    starts_at = min(starts_at, subscription.current_period_start)
    window = grant_window(
        SubscriptionStatus(subscription.status),
        starts_at=starts_at,
        current_period_end=subscription.current_period_end,
        grace_period_ends_at=subscription.grace_period_ends_at,
        now=now,
    )
    for key in product.entitlement_keys:
        statement = insert(SubscriptionEntitlement).values(
            user_id=subscription.user_id,
            entitlement_key=key,
            source_type=GrantSource.SUBSCRIPTION,
            source_id=subscription.id,
            starts_at=starts_at,
            ends_at=window.ends_at,
            revoked_at=window.revoked_at,
        )
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[
                    SubscriptionEntitlement.source_type,
                    SubscriptionEntitlement.source_id,
                    SubscriptionEntitlement.entitlement_key,
                ],
                set_={"ends_at": window.ends_at, "revoked_at": window.revoked_at},
            )
        )


class BillingService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        clock: Clock,
        providers: Mapping[str, BillingProvider],
    ) -> None:
        self._sessionmaker = sessionmaker
        self._clock = clock
        self._providers = dict(providers)

    async def products(self, platform_name: str) -> list[ProductOut]:
        async with self._sessionmaker() as session:
            rows = await session.scalars(
                select(Product)
                .where(Product.platform == platform_name, Product.active.is_(True))
                .order_by(Product.period.nulls_last(), Product.sku)
            )
            return [_product_out(row) for row in rows]

    async def entitlements(self, user_id: uuid.UUID) -> Entitlements:
        async with self._sessionmaker() as session:
            return await get_entitlements(session, user_id, at=self._clock.now())

    def _provider(self, store: str) -> BillingProvider:
        provider = self._providers.get(store)
        if provider is None:
            raise AppError(ErrorCode.SERVICE_UNAVAILABLE, "Purchases can't be verified yet.")
        return provider

    async def verify(
        self, principal: Principal, claim: PurchaseClaim, *, idempotency_key: uuid.UUID
    ) -> VerifyPurchaseResult:
        now = self._clock.now()
        transaction = self._provider(claim.store).verify(claim, now=now)
        async with self._sessionmaker() as session, session.begin():
            replay = await platform.idempotency.claim(
                session,
                user_id=principal.user_id,
                key=idempotency_key,
                route=VERIFY_ROUTE,
                payload={"store": claim.store, "payload": claim.payload, "sku": claim.sku},
            )
            if replay is not None:
                return VerifyPurchaseResult.model_validate(replay.body)
            purchase = await self._apply(session, principal.user_id, claim.store, transaction, now)
            result = VerifyPurchaseResult(
                purchase=purchase,
                entitlements=await get_entitlements(session, principal.user_id, at=now),
            )
            await platform.idempotency.complete(
                session,
                user_id=principal.user_id,
                key=idempotency_key,
                status=200,
                body=result.model_dump(mode="json", by_alias=True),
            )
        return result

    async def restore(
        self, principal: Principal, claims: Sequence[PurchaseClaim], *, idempotency_key: uuid.UUID
    ) -> Entitlements:
        """Re-verify each transaction; ones bound to another account are skipped (docs/07 §6)."""
        now = self._clock.now()
        verified = [self._provider(c.store).verify(c, now=now) for c in claims]
        async with self._sessionmaker() as session, session.begin():
            replay = await platform.idempotency.claim(
                session,
                user_id=principal.user_id,
                key=idempotency_key,
                route=RESTORE_ROUTE,
                payload={"count": len(claims), "first": claims[0].payload if claims else None},
            )
            if replay is not None:
                return Entitlements.model_validate(replay.body)
            for claim, transaction in zip(claims, verified, strict=True):
                try:
                    async with session.begin_nested():
                        await self._apply(session, principal.user_id, claim.store, transaction, now)
                except AppError as exc:
                    if exc.code is not ErrorCode.PURCHASE_ALREADY_LINKED:
                        raise
            result = await get_entitlements(session, principal.user_id, at=now)
            await platform.idempotency.complete(
                session,
                user_id=principal.user_id,
                key=idempotency_key,
                status=200,
                body=result.model_dump(mode="json", by_alias=True),
            )
        return result

    async def _apply(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        store: str,
        transaction: StoreTransaction,
        now: datetime,
    ) -> PurchaseOut:
        platform_name = {"apple": "ios", "google": "android"}.get(store, "ios")
        product = await session.scalar(
            select(Product).where(Product.platform == platform_name, Product.sku == transaction.sku)
        )
        if product is None or not product.active:
            raise AppError(ErrorCode.PURCHASE_INVALID, "This product isn't sold here.")
        kind = (
            "subscription_purchase"
            if product.kind == ProductKind.AUTO_RENEWABLE
            else "non_consumable"
        )
        if product.kind == ProductKind.AUTO_RENEWABLE:
            await self._upsert_subscription(session, user_id, product, transaction, now)
        inserted = await session.execute(
            insert(Purchase)
            .values(
                user_id=user_id,
                provider=transaction.provider,
                product_id=product.id,
                transaction_id=transaction.transaction_id,
                kind=kind,
                purchased_at=transaction.purchased_at,
                environment=transaction.environment,
            )
            .on_conflict_do_nothing(index_elements=[Purchase.provider, Purchase.transaction_id])
            .returning(Purchase.id)
        )
        purchase_id = inserted.scalar_one_or_none()
        if purchase_id is None:
            row = await session.scalar(
                select(Purchase).where(
                    Purchase.provider == transaction.provider,
                    Purchase.transaction_id == transaction.transaction_id,
                )
            )
            assert row is not None
            if row.user_id != user_id:
                raise AppError(
                    ErrorCode.PURCHASE_ALREADY_LINKED, "This purchase belongs to another account."
                )
            purchase_id = row.id
        if product.kind == ProductKind.NON_CONSUMABLE:
            await self._grant_content(session, user_id, product, purchase_id, transaction)
        return PurchaseOut(
            id=purchase_id,
            provider=transaction.provider,  # type: ignore[arg-type]
            product_sku=product.sku,
            kind=kind,  # type: ignore[arg-type]
            status="verified",
            purchased_at=transaction.purchased_at,
        )

    async def _upsert_subscription(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        product: Product,
        transaction: StoreTransaction,
        now: datetime,
    ) -> Subscription:
        subscription = await session.scalar(
            select(Subscription)
            .where(
                Subscription.provider == transaction.provider,
                Subscription.original_transaction_id == transaction.original_transaction_id,
            )
            .with_for_update()
        )
        period = PERIODS.get(product.period or "P1M", PERIODS["P1M"])
        if subscription is not None and subscription.user_id != user_id:
            # Receipt sharing: one store transaction, one account (docs/07 §6.3).
            raise AppError(
                ErrorCode.PURCHASE_ALREADY_LINKED, "This purchase belongs to another account."
            )
        if subscription is None:
            subscription = Subscription(
                user_id=user_id,
                provider=transaction.provider,
                product_id=product.id,
                original_transaction_id=transaction.original_transaction_id,
                status=transaction.status,
                auto_renew_enabled=transaction.auto_renew,
                current_period_start=transaction.purchased_at,
                current_period_end=transaction.purchased_at + period,
                environment=transaction.environment,
                last_event_at=now,
            )
            session.add(subscription)
            await session.flush()
            await session.refresh(subscription)
        else:
            subscription.product_id = product.id
            subscription.status = transaction.status
            subscription.auto_renew_enabled = transaction.auto_renew
            if (subscription.current_period_end or now) <= now:
                subscription.current_period_start = transaction.purchased_at
                subscription.current_period_end = transaction.purchased_at + period
            subscription.last_event_at = now
            await session.flush()
        if transaction.status == SubscriptionStatus.IN_GRACE_PERIOD:
            subscription.grace_period_ends_at = now + GRACE
        await _materialize(session, subscription, product, now=now)
        return subscription

    async def _grant_content(
        self,
        session: AsyncSession,
        user_id: uuid.UUID,
        product: Product,
        purchase_id: uuid.UUID,
        transaction: StoreTransaction,
    ) -> None:
        """Permanent grants for a non-consumable purchase (docs/07 §2)."""
        for key in product.entitlement_keys:
            await session.execute(
                insert(SubscriptionEntitlement)
                .values(
                    user_id=user_id,
                    entitlement_key=key,
                    source_type=GrantSource.PURCHASE,
                    source_id=purchase_id,
                    starts_at=transaction.purchased_at,
                )
                .on_conflict_do_nothing()
            )

    async def apply_event(
        self,
        *,
        provider: str,
        provider_event_id: str,
        original_transaction_id: str,
        event: StoreEvent,
        signed_date: datetime | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> str:
        """Apply one normalized store notification; returns ``processed`` or ``ignored``."""
        now = self._clock.now()
        signed_date = signed_date or now
        async with self._sessionmaker() as session, session.begin():
            stored = await session.execute(
                insert(BillingEvent)
                .values(
                    provider=provider,
                    provider_event_id=provider_event_id,
                    event_type=event.value,
                    signed_date=signed_date,
                    payload=dict(payload or {}),
                )
                .on_conflict_do_nothing(
                    index_elements=[BillingEvent.provider, BillingEvent.provider_event_id]
                )
                .returning(BillingEvent.id)
            )
            event_id = stored.scalar_one_or_none()
            if event_id is None:
                existing = await session.scalar(
                    select(BillingEvent.processing_status).where(
                        BillingEvent.provider == provider,
                        BillingEvent.provider_event_id == provider_event_id,
                    )
                )
                return str(existing)  # duplicate delivery
            subscription = await session.scalar(
                select(Subscription)
                .where(
                    Subscription.provider == provider,
                    Subscription.original_transaction_id == original_transaction_id,
                )
                .with_for_update()
            )
            outcome = "ignored"
            if subscription is not None and (
                subscription.last_event_at is None or signed_date >= subscription.last_event_at
            ):
                target = next_status(SubscriptionStatus(subscription.status), event)
                if target is not None:
                    product = await session.get(Product, subscription.product_id)
                    assert product is not None
                    self._transition(subscription, product, event, target, signed_date, now)
                    await session.flush()
                    await _materialize(session, subscription, product, now=signed_date)
                    outcome = "processed"
            await session.execute(
                update(BillingEvent)
                .where(BillingEvent.id == event_id)
                .values(
                    subscription_id=subscription.id if subscription else None,
                    processing_status=outcome,
                    processed_at=func.now(),
                    attempts=1,
                )
            )
        return outcome

    @staticmethod
    def _transition(
        subscription: Subscription,
        product: Product,
        event: StoreEvent,
        target: SubscriptionStatus,
        at: datetime,
        now: datetime,
    ) -> None:
        period = PERIODS.get(product.period or "P1M", PERIODS["P1M"])
        if event is StoreEvent.RENEWED:
            start = max(subscription.current_period_end or at, at)
            subscription.current_period_start = start
            subscription.current_period_end = start + period
            subscription.grace_period_ends_at = None
        elif event is StoreEvent.GRACE:
            subscription.grace_period_ends_at = at + GRACE
        elif event is StoreEvent.AUTO_RENEW_OFF:
            subscription.auto_renew_enabled = False
            subscription.cancelled_at = at
        elif event is StoreEvent.AUTO_RENEW_ON:
            subscription.auto_renew_enabled = True
            subscription.cancelled_at = None
        elif event is StoreEvent.EXPIRED:
            subscription.expired_at = at
        elif event is StoreEvent.REFUNDED:
            subscription.revoked_at = at
        if event in (StoreEvent.RECOVERED, StoreEvent.RESUMED):
            subscription.grace_period_ends_at = None
        subscription.status = target
        subscription.last_event_at = at
        del now


async def purge_expired(session: AsyncSession) -> int:
    """Processed store notifications after 90 days (the subscription keeps the state)."""
    return await platform.delete_batch(
        session,
        BillingEvent,
        (BillingEvent.processing_status.in_(["processed", "ignored"]))
        & (BillingEvent.received_at < platform.ago(days=90)),
    )


__all__ = [
    "BillingService",
    "Feature",
    "Quota",
    "get_entitlements",
    "group_premium",
    "has",
    "quota_limit",
    "snapshot",
    "timedelta",
]
