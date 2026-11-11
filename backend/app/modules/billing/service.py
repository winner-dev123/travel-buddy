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

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.i18n import negotiate_ui_locale
from app.core.pagination import CursorCodec, PageInfo, clamp_limit
from app.core.security.principal import Principal
from app.core.time import Clock
from app.modules.billing.apple import (
    AppleJWSVerifier,
    AppleSignatureError,
    notification_event,
)
from app.modules.billing.apple import signed_date as apple_signed_date
from app.modules.billing.domain import (
    GRACE,
    ProductKind,
    StoreEvent,
    SubscriptionStatus,
    add_period,
    grant_window,
    management,
    next_status,
    period_length,
)
from app.modules.billing.entitlements import (
    DEFAULT_POLICY,
    DEFAULT_QUOTAS,
    EntitlementPolicy,
    EntitlementSnapshot,
    Feature,
    Grant,
    GrantSource,
    GroupPremiumStatus,
    Plan,
    Quota,
    QuotaRule,
    evaluate,
    group_premium_status,
)
from app.modules.billing.google import (
    REVOKING_NOTIFICATIONS,
    GoogleAuthError,
    GooglePlayError,
    GooglePlayProvider,
    PlaySubscription,
    PushVerifier,
    parse_push,
)
from app.modules.billing.models import (
    BillingCustomer,
    BillingEvent,
    BillingTransaction,
    CheckoutSession,
    EntitlementPolicyOverride,
    Product,
    Purchase,
    Subscription,
    SubscriptionEntitlement,
)
from app.modules.billing.providers import BillingProvider, PurchaseClaim, StoreTransaction
from app.modules.billing.schemas import (
    ActiveSubscription,
    AdminProductOut,
    BillingPolicyOut,
    CreateProductRequest,
    EntitlementFeatures,
    EntitlementGrantOut,
    EntitlementQuotas,
    Entitlements,
    PolicyQuotaOut,
    ProductOut,
    ProductPrice,
    PurchaseOut,
    QuotaStatusOut,
    TransactionOut,
    TransactionPage,
    TransactionProduct,
    UpdateBillingPolicyRequest,
    UpdateProductRequest,
    VerifyPurchaseResult,
)
from app.modules.billing.stripe import (
    HANDLED_EVENTS,
    StripeCharge,
    StripeCheckout,
    StripeClient,
    StripeDispute,
    StripeInvoice,
    StripeSubscription,
    verify_signature,
)
from app.modules.platform import service as platform

# (session, user, at) -> current usage per quota, from the modules that own the counted rows.
QuotaUsage = Callable[[AsyncSession, uuid.UUID, datetime], Awaitable[Mapping[Quota, int]]]

VERIFY_ROUTE = "POST /v1/billing/purchases/verify"

logger = logging.getLogger(__name__)

# Hosted Checkout sessions live an hour; an open one is handed out again until 5 minutes before
# it expires (BILL-006).
CHECKOUT_LIFETIME = timedelta(hours=1)
CHECKOUT_REUSE_MARGIN = timedelta(minutes=5)
RECONCILE_JOB = "billing.stripe_reconcile"
REMINDERS_JOB = "billing.expiry_reminders"
NOTICE_EVENT = "billing.notice"
# Premium ending in this window gets one reminder from the daily job.
REMINDER_WINDOW = (timedelta(hours=48), timedelta(hours=72))
# The ledger never moves backwards: a late "failed" can't undo a "succeeded" (BILL-011).
_STATUS_RANK = {"pending": 0, "open": 0, "failed": 1, "succeeded": 2, "won": 2, "lost": 2}
_INVOICE_REASONS = {
    "subscription_create": "purchase",
    "subscription_cycle": "renewal",
    "subscription_update": "change",
}
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


def _policy_from(row: EntitlementPolicyOverride | None) -> EntitlementPolicy:
    """The code defaults with the stored overrides applied (unknown keys are ignored, so a
    rolled-back deploy still reads a newer row)."""
    if row is None:
        return DEFAULT_POLICY
    quotas: dict[Quota, QuotaRule] = dict(DEFAULT_QUOTAS)
    for key, limits in (row.quotas or {}).items():
        try:
            quota = Quota(key)
            quotas[quota] = QuotaRule(
                free=int(limits["free"]),
                premium=int(limits["premium"]),
                period=DEFAULT_QUOTAS[quota].period,
            )
        except (ValueError, KeyError, TypeError):
            continue
    grace = (
        timedelta(days=row.group_admin_grace_days)
        if row.group_admin_grace_days is not None
        else DEFAULT_POLICY.group_admin_grace_period
    )
    return EntitlementPolicy(
        free_features=DEFAULT_POLICY.free_features,
        premium_features=DEFAULT_POLICY.premium_features,
        quotas=quotas,
        group_admin_grace_period=grace,
    )


async def current_policy(session: AsyncSession) -> EntitlementPolicy:
    """The policy in force: defaults in code, overrides edited at runtime by staff (BL-6.02)."""
    return _policy_from(await session.get(EntitlementPolicyOverride, 1))


async def snapshot(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    at: datetime,
    policy: EntitlementPolicy | None = None,
) -> EntitlementSnapshot:
    if policy is None:
        policy = await current_policy(session)
    return evaluate(await _load_grants(session, user_id), at=at, policy=policy)


async def has(session: AsyncSession, user_id: uuid.UUID, feature: Feature, *, at: datetime) -> bool:
    return (await snapshot(session, user_id, at=at)).has(feature)


async def group_premium(
    session: AsyncSession, owner_id: uuid.UUID | None, *, at: datetime
) -> GroupPremiumStatus:
    """A group's premium status from its owner's grants, with the admin grace (docs/07 §5). A
    group without an owner (archived after the owner's account was erased) has none."""
    grants = await _load_grants(session, owner_id) if owner_id is not None else []
    return group_premium_status(grants, at=at, policy=await current_policy(session))


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


def _localized(text: Mapping[str, str] | None, preferences: Sequence[str]) -> str | None:
    """The first preferred locale the text has, then English, then anything."""
    if not text:
        return None
    for tag in (*preferences, "en"):
        found = text.get(negotiate_ui_locale(tag))
        if found:
            return found
    return next(iter(text.values()), None)


def _product_out(
    row: Product, preferences: Sequence[str] = (), price: ProductPrice | None = None
) -> ProductOut:
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
            "title": _localized(row.title, preferences),
            "description": _localized(row.description, preferences),
            "price": price,
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
        stripe: StripeClient | None = None,
        web_origin: str = "http://localhost:3000",
        usage: QuotaUsage | None = None,
        apple: AppleJWSVerifier | None = None,
        google: GooglePlayProvider | None = None,
        google_push: PushVerifier | None = None,
        cursors: CursorCodec | None = None,
        partial_refund_revokes: bool = False,
        refund_duplicates: bool = True,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._cursors = cursors
        self._partial_refund_revokes = partial_refund_revokes
        self._refund_duplicates = refund_duplicates
        self._clock = clock
        self._providers = dict(providers)
        self._stripe = stripe
        self._apple = apple
        self._google = google
        self._google_push = google_push
        self._web_origin = web_origin.rstrip("/")
        self._usage = usage

    async def _entitlements(
        self, session: AsyncSession, user_id: uuid.UUID, at: datetime
    ) -> Entitlements:
        usage = await self._usage(session, user_id, at) if self._usage is not None else None
        return await get_entitlements(session, user_id, at=at, usage=usage)

    async def products(
        self, platform_name: str, preferences: Sequence[str] = ()
    ) -> list[ProductOut]:
        """Offers in display order (BILL-010). Web offers carry Stripe's price; store apps show
        the store's own localized price."""
        async with self._sessionmaker() as session:
            rows = list(
                await session.scalars(
                    select(Product)
                    .where(Product.platform == platform_name, Product.active.is_(True))
                    .order_by(Product.sort_order, Product.period.nulls_last(), Product.sku)
                )
            )
        prices: list[ProductPrice | None] = [None] * len(rows)
        stripe = self._stripe
        if platform_name == "web" and stripe is not None and stripe.configured:
            found = await asyncio.gather(*(stripe.price(row.sku) for row in rows))
            prices = [
                ProductPrice(amount_minor=p.unit_amount, currency=p.currency, recurring=p.recurring)
                if p is not None and p.unit_amount is not None and p.currency
                else None
                for p in found
            ]
        return [
            _product_out(row, preferences, price) for row, price in zip(rows, prices, strict=True)
        ]

    async def entitlements(self, user_id: uuid.UUID) -> Entitlements:
        async with self._sessionmaker() as session:
            return await self._entitlements(session, user_id, self._clock.now())

    def _provider(self, store: str) -> BillingProvider:
        provider = self._providers.get(store)
        if provider is None:
            raise AppError(ErrorCode.SERVICE_UNAVAILABLE, "Purchases can't be verified yet.")
        return provider

    async def _with_kind(self, claim: PurchaseClaim) -> PurchaseClaim:
        """Google answers subscriptions and one-time products on different APIs: tell it which
        one this SKU is, from the catalog."""
        if claim.store != "google":
            return claim
        async with self._sessionmaker() as session:
            kind = await session.scalar(
                select(Product.kind).where(
                    Product.platform == "android",
                    Product.sku == claim.sku,
                    Product.active.is_(True),
                )
            )
        if kind is None:
            raise AppError(ErrorCode.PURCHASE_INVALID, "This product isn't sold here.")
        return replace(claim, product_kind=str(kind))

    async def verify(
        self, principal: Principal, claim: PurchaseClaim, *, idempotency_key: uuid.UUID
    ) -> VerifyPurchaseResult:
        now = self._clock.now()
        claim = await self._with_kind(claim)
        transaction = await self._provider(claim.store).verify(claim, now=now)
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
                entitlements=await self._entitlements(session, principal.user_id, now),
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
        verified = [
            await self._provider(c.store).verify(await self._with_kind(c), now=now) for c in claims
        ]
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
            result = await self._entitlements(session, principal.user_id, now)
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
        kind = {
            ProductKind.AUTO_RENEWABLE: "subscription_purchase",
            ProductKind.NON_RENEWING: "non_renewing",
        }.get(ProductKind(product.kind), "non_consumable")
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
        else:
            await _record_transaction(
                session,
                user_id=user_id,
                provider=transaction.provider,
                environment=transaction.environment,
                kind="payment",
                status="succeeded",
                reference=transaction.transaction_id,
                product_id=product.id,
                purchase_id=purchase_id,
                reason="purchase",
                occurred_at=transaction.purchased_at,
            )
        if product.kind == ProductKind.NON_CONSUMABLE:
            await self._grant_content(session, user_id, product, purchase_id, transaction)
        elif product.kind == ProductKind.NON_RENEWING:
            await _grant_pass(session, user_id, product, purchase_id, transaction.purchased_at)
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
        period = period_length(product.period)
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
                current_period_end=transaction.expires_at or transaction.purchased_at + period,
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
            if transaction.expires_at is not None:
                subscription.current_period_end = transaction.expires_at
            elif (subscription.current_period_end or now) <= now:
                subscription.current_period_start = transaction.purchased_at
                subscription.current_period_end = transaction.purchased_at + period
            subscription.last_event_at = now
            await session.flush()
        if transaction.status == SubscriptionStatus.IN_GRACE_PERIOD:
            subscription.grace_period_ends_at = transaction.expires_at or now + GRACE
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
        await _grant_permanent(session, user_id, product, purchase_id, transaction.purchased_at)

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

    # ─────────────────────────── App Store notifications (BL-6.01) ───────────────────────────

    async def apple_webhook(self, signed_payload: str) -> str:
        """App Store Server Notifications v2 (BILL-007, BILL-008): verified against the pinned
        Apple root, stored once per ``notificationUUID`` and applied; ``ignored`` for types that
        change nothing. ``400`` for anything not signed by Apple for this app."""
        if self._apple is None:
            raise AppError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "App Store notifications aren't set up yet.",
                headers={"Retry-After": "3600"},
            )
        now = self._clock.now()
        try:
            notification = self._apple.decode(signed_payload, now=now)
            data = notification.get("data") or {}
            if data.get("bundleId") != self._apple.bundle_id:
                raise AppleSignatureError("another app")
            info = data.get("signedTransactionInfo")
            tx = self._apple.decode(info, now=now) if info else None
        except AppleSignatureError:
            raise AppError(
                ErrorCode.BAD_REQUEST, "The notification isn't signed by Apple."
            ) from None
        kind, subtype = str(notification.get("notificationType")), notification.get("subtype")
        event = notification_event(kind, subtype)
        if event is None or tx is None:
            return "ignored"
        return await self.apply_event(
            provider="apple",
            provider_event_id=str(notification["notificationUUID"]),
            original_transaction_id=str(tx["originalTransactionId"]),
            event=event,
            # A store event can't be from our future (clock skew would delay its effect).
            signed_date=min(apple_signed_date(notification) or now, now),
            payload={
                "notification_type": kind,
                "subtype": subtype,
                "transaction_id": tx.get("transactionId"),
                "environment": data.get("environment"),
            },
        )

    # ─────────────────────────── Google Play notifications (BL-6.01) ───────────────────────────

    async def google_webhook(self, body: Mapping[str, Any], authorization: str | None) -> str:
        """Real-time Developer Notifications through Pub/Sub push (BILL-007, BILL-008). The push
        OIDC token is checked first; each message is stored once by ``messageId``; the state is
        re-read from the Play Developer API. A Play API failure answers ``503`` so Pub/Sub retries
        (nothing is stored in that case)."""
        if self._google is None or self._google_push is None:
            raise AppError(
                ErrorCode.SERVICE_UNAVAILABLE,
                "Google Play notifications aren't set up yet.",
                headers={"Retry-After": "3600"},
            )
        try:
            await self._google_push.verify(authorization)
        except GoogleAuthError:
            raise AppError(ErrorCode.UNAUTHENTICATED, "Not a Pub/Sub push for this app.") from None
        try:
            note = parse_push(body)
        except ValueError:
            raise AppError(ErrorCode.BAD_REQUEST, "The push message isn't readable.") from None
        now = self._clock.now()
        handled = note.package_name == self._google.package_name and note.kind in (
            "subscription",
            "voided",
        )
        async with self._sessionmaker() as session, session.begin():
            stored = await session.execute(
                insert(BillingEvent)
                .values(
                    provider="google",
                    provider_event_id=note.message_id,
                    event_type=f"{note.kind}:{note.notification_type or 0}",
                    signed_date=min(note.published_at or now, now),
                    payload={
                        "kind": note.kind,
                        "notification_type": note.notification_type,
                        "sku": note.sku,
                        "package_name": note.package_name,
                    },
                )
                .on_conflict_do_nothing(
                    index_elements=[BillingEvent.provider, BillingEvent.provider_event_id]
                )
                .returning(BillingEvent.id)
            )
            event_id = stored.scalar_one_or_none()
            if event_id is None:
                return "duplicate"
            row_id: uuid.UUID | None = None
            outcome = "ignored"
            if handled and note.purchase_token:
                if note.kind == "voided":
                    row_id, outcome = await self._void_google(
                        session, note.purchase_token, note.order_id, now
                    )
                else:
                    try:
                        fresh: PlaySubscription | None = await self._google.subscription_state(
                            note.purchase_token
                        )
                    except GooglePlayError:
                        raise AppError(
                            ErrorCode.SERVICE_UNAVAILABLE,
                            "Google Play is unavailable; the notification will be retried.",
                            headers={"Retry-After": "60"},
                        ) from None
                    except AppError as exc:  # Play doesn't know the token: nothing to apply
                        if exc.code is not ErrorCode.PURCHASE_INVALID:
                            raise
                        fresh = None
                    if fresh is not None:
                        revoke = note.notification_type in REVOKING_NOTIFICATIONS
                        row_id = await self._apply_google(session, fresh, revoke=revoke, now=now)
                    outcome = "processed" if row_id else "ignored"
            await session.execute(
                update(BillingEvent)
                .where(BillingEvent.id == event_id)
                .values(
                    subscription_id=row_id,
                    processing_status=outcome,
                    processed_at=func.now(),
                    attempts=1,
                )
            )
        return outcome

    async def _apply_google(
        self, session: AsyncSession, fresh: PlaySubscription, *, revoke: bool, now: datetime
    ) -> uuid.UUID | None:
        """Mirror the Play state onto the subscription the purchase token belongs to. Unknown
        tokens (not verified by the app yet) are ignored: verification reads the same state."""
        subscription = await session.scalar(
            select(Subscription)
            .where(
                Subscription.provider == "google",
                Subscription.original_transaction_id == fresh.purchase_token,
            )
            .with_for_update()
        )
        if subscription is None:
            return None
        product = await session.get(Product, subscription.product_id)
        assert product is not None
        if revoke:
            subscription.status = SubscriptionStatus.REVOKED
            subscription.revoked_at = now
        elif subscription.status != SubscriptionStatus.REVOKED and fresh.status is not None:
            subscription.status = fresh.status
        subscription.auto_renew_enabled = fresh.auto_renew
        subscription.cancelled_at = None if fresh.auto_renew else subscription.cancelled_at or now
        if fresh.expires_at is not None:
            subscription.current_period_end = fresh.expires_at
        subscription.grace_period_ends_at = (
            fresh.expires_at if subscription.status == SubscriptionStatus.IN_GRACE_PERIOD else None
        )
        if subscription.status == SubscriptionStatus.EXPIRED and subscription.expired_at is None:
            subscription.expired_at = now
        subscription.last_event_at = now
        await session.flush()
        await session.refresh(subscription)
        await _materialize(session, subscription, product, now=now)
        return subscription.id

    async def _void_google(
        self, session: AsyncSession, token: str, order_id: str | None, now: datetime
    ) -> tuple[uuid.UUID | None, str]:
        """A refunded or charged-back Play purchase ends its access at once: the subscription,
        or the content a one-time purchase unlocked."""
        subscription = await session.scalar(
            select(Subscription)
            .where(Subscription.provider == "google", Subscription.original_transaction_id == token)
            .with_for_update()
        )
        if subscription is not None:
            subscription.status = SubscriptionStatus.REVOKED
            subscription.revoked_at = now
            subscription.last_event_at = now
            product = await session.get(Product, subscription.product_id)
            assert product is not None
            await session.flush()
            await _materialize(session, subscription, product, now=now)
            return subscription.id, "processed"
        if order_id is None:
            return None, "ignored"
        revoked = await session.execute(
            update(SubscriptionEntitlement)
            .where(
                SubscriptionEntitlement.source_type == GrantSource.PURCHASE,
                SubscriptionEntitlement.source_id.in_(
                    select(Purchase.id).where(
                        Purchase.provider == "google", Purchase.transaction_id == order_id
                    )
                ),
                SubscriptionEntitlement.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        return None, "processed" if revoked.rowcount else "ignored"  # type: ignore[attr-defined]

    # ─────────────────────────── web: Stripe (BL-3.14, ADR-0012) ───────────────────────────

    def _require_stripe(self) -> StripeClient:
        if self._stripe is None or not self._stripe.configured:
            raise AppError(ErrorCode.SERVICE_UNAVAILABLE, "Web payments aren't available yet.")
        return self._stripe

    async def checkout(
        self,
        principal: Principal,
        *,
        product_id: uuid.UUID,
        success_path: str,
        cancel_path: str,
        idempotency_key: uuid.UUID,
    ) -> tuple[str, datetime | None]:
        """A hosted Checkout URL. Completing it grants nothing: only the webhook does. An open
        session for the same offer is handed out again, so a second tab or a retry never starts a
        second payment; checkouts of one user are serialized for that (BILL-006)."""
        stripe = self._require_stripe()
        me, now = principal.user_id, self._clock.now()
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                select(func.pg_advisory_xact_lock(func.hashtext(f"billing.checkout:{me}")))
            )
            product = await session.get(Product, product_id)
            if product is None or product.platform != "web" or not product.active:
                raise AppError(ErrorCode.NOT_FOUND, "Product not found.")
            await _refuse_double_purchase(session, me, product, now)
            reusable = await session.scalar(
                select(CheckoutSession)
                .where(
                    CheckoutSession.user_id == me,
                    CheckoutSession.product_id == product.id,
                    CheckoutSession.status == "open",
                    CheckoutSession.expires_at > now + CHECKOUT_REUSE_MARGIN,
                )
                .order_by(CheckoutSession.created_at.desc())
                .limit(1)
            )
            if reusable is not None:
                return reusable.url, reusable.expires_at
            customer = await _stripe_customer(session, me)
            if customer is None:
                customer = await stripe.create_customer(
                    user_id=str(me), idempotency_key=f"customer-{me}"
                )
                await session.execute(
                    insert(BillingCustomer)
                    .values(user_id=me, provider="stripe", provider_customer_id=customer)
                    .on_conflict_do_nothing()
                )
            started = await stripe.create_checkout_session(
                customer=customer,
                price_id=product.sku,
                mode="subscription" if product.kind == ProductKind.AUTO_RENEWABLE else "payment",
                user_id=str(me),
                product_id=str(product.id),
                success_url=f"{self._web_origin}{success_path}",
                cancel_url=f"{self._web_origin}{cancel_path}",
                expires_at=now + CHECKOUT_LIFETIME,
                idempotency_key=str(idempotency_key),
            )
            expires_at = started.expires_at or now + CHECKOUT_LIFETIME
            await session.execute(
                insert(CheckoutSession)
                .values(
                    user_id=me,
                    product_id=product.id,
                    provider_session_id=started.id,
                    url=started.url,
                    expires_at=expires_at,
                )
                .on_conflict_do_nothing(
                    index_elements=[CheckoutSession.provider, CheckoutSession.provider_session_id]
                )
            )
        return started.url, expires_at

    async def portal(self, principal: Principal, *, return_path: str | None) -> str:
        stripe = self._require_stripe()
        async with self._sessionmaker() as session:
            customer = await _stripe_customer(session, principal.user_id)
        if customer is None:
            raise AppError(ErrorCode.NOT_FOUND, "There's no web subscription to manage.")
        return await stripe.create_portal_session(
            customer=customer, return_url=f"{self._web_origin}{return_path or '/'}"
        )

    async def stripe_webhook(self, payload: bytes, signature: str | None) -> str:
        """Verify, fetch the object from Stripe, then store once by event ID and apply.

        Only the event's id, type, mode and object id come from the payload. A failure talking to
        Stripe answers 503 before anything is stored, so Stripe delivers the event again.
        """
        stripe = self._stripe
        if stripe is None or not stripe.webhook_secret:
            raise AppError(ErrorCode.SERVICE_UNAVAILABLE, "Web payments aren't available yet.")
        now = self._clock.now()
        verify_signature(payload, signature, stripe.webhook_secret, now=now)
        try:
            event = json.loads(payload)
        except ValueError:
            raise AppError(ErrorCode.BAD_REQUEST, "The event isn't JSON.") from None
        if not isinstance(event, dict) or not event.get("id"):
            raise AppError(ErrorCode.BAD_REQUEST, "The event has no id.")
        event_id, event_type = str(event["id"]), str(event.get("type"))
        obj = (event.get("data") or {}).get("object") or {}
        object_id = str(obj.get("id") or "") if isinstance(obj, dict) else ""
        created = event.get("created")
        signed = datetime.fromtimestamp(int(created), tz=UTC) if created else now
        expected = stripe.expected_livemode
        wrong_mode = expected is not None and bool(event.get("livemode")) != expected
        async with self._sessionmaker() as session:
            seen = await session.scalar(
                select(BillingEvent.id).where(
                    BillingEvent.provider == "stripe", BillingEvent.provider_event_id == event_id
                )
            )
        if seen is not None:
            return "duplicate"
        facts = None
        if event_type in HANDLED_EVENTS and object_id and not wrong_mode:
            facts = await _fetch_stripe_facts(stripe, event_type, object_id)
        duplicates: list[str] = []
        async with self._sessionmaker() as session, session.begin():
            stored = await session.execute(
                insert(BillingEvent)
                .values(
                    provider="stripe",
                    provider_event_id=event_id,
                    event_type=event_type,
                    signed_date=signed,
                    payload={"type": event_type, "object_id": object_id},
                )
                .on_conflict_do_nothing(
                    index_elements=[BillingEvent.provider, BillingEvent.provider_event_id]
                )
                .returning(BillingEvent.id)
            )
            stored_id = stored.scalar_one_or_none()
            if stored_id is None:
                return "duplicate"
            outcome, row_id = "ignored", None
            if facts is not None:
                outcome, row_id, duplicates = await self._apply_stripe_facts(session, facts, now)
            await session.execute(
                update(BillingEvent)
                .where(BillingEvent.id == stored_id)
                .values(
                    subscription_id=row_id,
                    processing_status=outcome,
                    processed_at=func.now(),
                    attempts=1,
                    error="wrong_mode" if wrong_mode else None,
                )
            )
        await self._cancel_duplicates(duplicates)
        return outcome

    async def _apply_stripe_facts(
        self, session: AsyncSession, facts: _StripeFacts, now: datetime
    ) -> tuple[str, uuid.UUID | None, list[str]]:
        """Apply one fetched event; returns (outcome, subscription row, duplicates to cancel)."""
        kind = facts.event_type
        outcomes: list[bool] = []
        row_id: uuid.UUID | None = None
        duplicates: list[str] = []
        if facts.subscription is not None and not kind.startswith("charge."):
            row_id = await self._apply_stripe(session, facts.subscription, now)
            outcomes.append(row_id is not None)
            if row_id is not None:
                duplicates = await _duplicate_web_subscriptions(session, row_id)
        if facts.checkout is not None:
            outcomes.append(await self._apply_checkout(session, facts.checkout, kind, now))
        if facts.invoice is not None and kind.startswith("invoice."):
            outcomes.append(
                await self._apply_invoice(
                    session, facts.invoice, row_id, paid=kind == "invoice.paid", now=now
                )
            )
        if facts.charge is not None and kind == "charge.refunded":
            outcomes.append(await self._apply_refund(session, facts.charge, facts.invoice, now))
        if facts.dispute is not None:
            outcomes.append(
                await self._apply_dispute(session, facts.dispute, facts.charge, facts.invoice, now)
            )
        return ("processed" if any(outcomes) else "ignored"), row_id, duplicates

    async def _apply_stripe(
        self, session: AsyncSession, fresh: StripeSubscription, now: datetime
    ) -> uuid.UUID | None:
        product = await session.scalar(
            select(Product).where(Product.platform == "web", Product.sku == fresh.price_id)
        )
        user_id = await _stripe_user(session, fresh.customer, fresh.user_id)
        if product is None or user_id is None:
            return None
        subscription = await session.scalar(
            select(Subscription)
            .where(
                Subscription.provider == "stripe", Subscription.original_transaction_id == fresh.id
            )
            .with_for_update()
        )
        if subscription is None:
            subscription = Subscription(
                user_id=user_id,
                provider="stripe",
                product_id=product.id,
                original_transaction_id=fresh.id,
                status=fresh.status,
                current_period_start=fresh.current_period_start,
                environment="production" if fresh.livemode else "sandbox",
            )
            session.add(subscription)
        subscription.product_id = product.id
        if subscription.status != SubscriptionStatus.REVOKED:
            subscription.status = fresh.status
        subscription.auto_renew_enabled = fresh.auto_renew
        subscription.current_period_start = fresh.current_period_start
        subscription.current_period_end = fresh.current_period_end
        subscription.grace_period_ends_at = (
            fresh.current_period_end if fresh.status == SubscriptionStatus.IN_GRACE_PERIOD else None
        )
        if fresh.status == SubscriptionStatus.EXPIRED and subscription.expired_at is None:
            subscription.expired_at = now
        subscription.last_event_at = now
        await session.flush()
        await session.refresh(subscription)
        await _materialize(session, subscription, product, now=now)
        return subscription.id

    async def _apply_checkout(
        self, session: AsyncSession, checkout: StripeCheckout, kind: str, now: datetime
    ) -> bool:
        """One-time web purchases and passes (``mode=payment``) are granted here; subscriptions
        through the subscription itself. Asynchronous methods (Pix, boleto) stay pending until
        Stripe confirms or fails them."""
        status = {"complete": "complete", "expired": "expired"}.get(checkout.status)
        changed = False
        if status is not None:
            marked = await session.execute(
                update(CheckoutSession)
                .where(
                    CheckoutSession.provider == "stripe",
                    CheckoutSession.provider_session_id == checkout.id,
                    CheckoutSession.status == "open",
                )
                .values(status=status, completed_at=now if status == "complete" else None)
            )
            changed = bool(marked.rowcount)  # type: ignore[attr-defined]
        if checkout.mode != "payment" or kind == "checkout.session.expired":
            return changed
        user_id = await _stripe_user(session, checkout.customer, checkout.user_id)
        product = await session.scalar(
            select(Product).where(Product.platform == "web", Product.sku == checkout.price_id)
        )
        if user_id is None or product is None:
            return changed
        environment = "production" if checkout.livemode else "sandbox"
        reference = checkout.payment_intent or checkout.id
        common: dict[str, Any] = {
            "user_id": user_id,
            "provider": "stripe",
            "environment": environment,
            "kind": "payment",
            "reference": reference,
            "product_id": product.id,
            "amount_minor": checkout.amount_total,
            "currency": checkout.currency,
            "reason": "purchase",
        }
        if checkout.payment_status in ("paid", "no_payment_required"):
            purchase_id = await _grant_web_purchase(
                session, user_id, product, reference, environment, now
            )
            await _record_transaction(
                session, **common, status="succeeded", purchase_id=purchase_id, occurred_at=now
            )
            if kind == "checkout.session.async_payment_succeeded":
                _notice(session, user_id, "payment_confirmed", reference)
            return True
        if kind == "checkout.session.async_payment_failed":
            await _record_transaction(session, **common, status="failed", occurred_at=now)
            _notice(session, user_id, "payment_failed", reference)
            return True
        await _record_transaction(session, **common, status="pending", occurred_at=now)
        return True

    async def _apply_invoice(
        self,
        session: AsyncSession,
        invoice: StripeInvoice,
        row_id: uuid.UUID | None,
        *,
        paid: bool,
        now: datetime,
    ) -> bool:
        """A subscription payment (first one or a renewal) in the ledger; a declined one also
        tells the traveller (BILL-011)."""
        user_id = await _stripe_user(session, invoice.customer, None)
        amount = invoice.amount_paid if paid else invoice.amount_due
        if user_id is None or not amount:
            return False  # $0 invoices (trials, prorations to nothing) aren't payments
        product_id = None
        if row_id is not None:
            product_id = await session.scalar(
                select(Subscription.product_id).where(Subscription.id == row_id)
            )
        await _record_transaction(
            session,
            user_id=user_id,
            provider="stripe",
            environment="production" if invoice.livemode else "sandbox",
            kind="payment",
            status="succeeded" if paid else "failed",
            reference=invoice.id,
            product_id=product_id,
            subscription_id=row_id,
            amount_minor=amount,
            currency=invoice.currency,
            reason=_INVOICE_REASONS.get(invoice.billing_reason or "", invoice.billing_reason),
            receipt_url=invoice.hosted_invoice_url,
            occurred_at=(invoice.paid_at or now) if paid else now,
        )
        if not paid:
            _notice(session, user_id, "payment_failed", invoice.id)
        return True

    async def _apply_refund(
        self,
        session: AsyncSession,
        charge: StripeCharge,
        invoice: StripeInvoice | None,
        now: datetime,
    ) -> bool:
        """Record the refund; a full one (or a partial one, when configured) revokes exactly what
        it paid for: the invoice's subscription or the one-time purchase (docs/07 §8)."""
        user_id = await _stripe_user(session, charge.customer, None)
        if user_id is None:
            return False
        environment = "production" if charge.livemode else "sandbox"
        await _record_transaction(
            session,
            user_id=user_id,
            provider="stripe",
            environment=environment,
            kind="refund",
            status="succeeded",
            reference=charge.id,
            amount_minor=charge.amount_refunded,
            currency=charge.currency,
            reason="refund" if charge.fully_refunded else "partial_refund",
            receipt_url=charge.receipt_url,
            occurred_at=now,
        )
        revokes = charge.fully_refunded or self._partial_refund_revokes
        if revokes and await _revoke_paid_by(session, charge, invoice, now):
            _notice(session, user_id, "refunded", charge.id)
        return True

    async def _apply_dispute(
        self,
        session: AsyncSession,
        dispute: StripeDispute,
        charge: StripeCharge | None,
        invoice: StripeInvoice | None,
        now: datetime,
    ) -> bool:
        """Chargebacks: recorded while open; a lost one revokes like a full refund."""
        user_id = await _stripe_user(session, charge.customer if charge else None, None)
        if user_id is None:
            return False
        await _record_transaction(
            session,
            user_id=user_id,
            provider="stripe",
            environment="production" if dispute.livemode else "sandbox",
            kind="dispute",
            status=dispute.outcome,
            reference=dispute.id,
            amount_minor=dispute.amount,
            currency=dispute.currency,
            reason=dispute.reason,
            occurred_at=now,
        )
        if dispute.outcome == "lost" and charge is not None:
            await _revoke_paid_by(session, charge, invoice, now)
        return True

    async def _cancel_duplicates(self, subscription_ids: Sequence[str]) -> None:
        """A second web subscription to the same plan (two tabs paid at once): cancel it now and
        refund its first payment. Stripe then sends the cancellation and the refund back to us.
        Failures are left for the daily reconciliation."""
        stripe = self._stripe
        if stripe is None or not stripe.configured:
            return
        for subscription_id in subscription_ids:
            try:
                fresh = await stripe.get_subscription(subscription_id)
                await stripe.cancel_subscription(
                    subscription_id, idempotency_key=f"duplicate-cancel-{subscription_id}"
                )
                if self._refund_duplicates and fresh.latest_invoice:
                    invoice = await stripe.get_invoice(fresh.latest_invoice)
                    if invoice.payment_intent and invoice.amount_paid:
                        await stripe.refund(
                            invoice.payment_intent,
                            reason="duplicate",
                            idempotency_key=f"duplicate-refund-{subscription_id}",
                        )
            except AppError as exc:
                logger.warning(
                    "duplicate web subscription not cancelled", extra={"error": exc.code}
                )

    async def reconcile_stripe(self, *, limit: int = 200) -> int:
        """Daily safety net: re-read the web subscriptions that still grant something, cancel
        duplicates that slipped through and close Checkout sessions that ran out (BILL-006)."""
        stripe = self._stripe
        now = self._clock.now()
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                update(CheckoutSession)
                .where(CheckoutSession.status == "open", CheckoutSession.expires_at <= now)
                .values(status="expired")
            )
        if stripe is None or not stripe.configured:
            return 0
        async with self._sessionmaker() as session:
            references = list(
                await session.scalars(
                    select(Subscription.original_transaction_id)
                    .where(
                        Subscription.provider == "stripe",
                        Subscription.status.in_(
                            [
                                SubscriptionStatus.ACTIVE,
                                SubscriptionStatus.IN_GRACE_PERIOD,
                                SubscriptionStatus.IN_BILLING_RETRY,
                                SubscriptionStatus.PAUSED,
                            ]
                        ),
                    )
                    .order_by(Subscription.last_event_at.nulls_first())
                    .limit(limit)
                )
            )
        updated = 0
        duplicates: list[str] = []
        for reference in references:
            try:
                fresh = await stripe.get_subscription(reference)
            except AppError:
                continue
            async with self._sessionmaker() as session, session.begin():
                row_id = await self._apply_stripe(session, fresh, now)
                if row_id is not None:
                    updated += 1
                    duplicates += await _duplicate_web_subscriptions(session, row_id)
        await self._cancel_duplicates(list(dict.fromkeys(duplicates)))
        return updated

    async def remind_expiring(self) -> int:
        """One reminder when Premium that won't renew ends in two to three days: passes, and
        subscriptions with auto-renew off. Runs daily, so each ending is seen once."""
        now = self._clock.now()
        low, high = now + REMINDER_WINDOW[0], now + REMINDER_WINDOW[1]
        reminded = 0
        async with self._sessionmaker() as session, session.begin():
            ending = (
                await session.execute(
                    select(
                        SubscriptionEntitlement.user_id,
                        SubscriptionEntitlement.source_type,
                        SubscriptionEntitlement.source_id,
                        SubscriptionEntitlement.ends_at,
                    ).where(
                        SubscriptionEntitlement.entitlement_key == "premium",
                        SubscriptionEntitlement.revoked_at.is_(None),
                        SubscriptionEntitlement.user_id.is_not(None),
                        SubscriptionEntitlement.ends_at > low,
                        SubscriptionEntitlement.ends_at <= high,
                        SubscriptionEntitlement.source_type.in_(
                            [GrantSource.SUBSCRIPTION, GrantSource.PURCHASE]
                        ),
                    )
                )
            ).all()
            for user_id, source_type, source_id, ends_at in ending:
                if source_type == GrantSource.SUBSCRIPTION:
                    renews = await session.scalar(
                        select(Subscription.auto_renew_enabled).where(Subscription.id == source_id)
                    )
                    if renews:
                        continue
                later = await session.scalar(
                    select(SubscriptionEntitlement.id)
                    .where(
                        SubscriptionEntitlement.user_id == user_id,
                        SubscriptionEntitlement.entitlement_key == "premium",
                        SubscriptionEntitlement.revoked_at.is_(None),
                        SubscriptionEntitlement.source_id != source_id,
                        SubscriptionEntitlement.starts_at <= ends_at,
                        or_(
                            SubscriptionEntitlement.ends_at.is_(None),
                            SubscriptionEntitlement.ends_at > ends_at,
                        ),
                    )
                    .limit(1)
                )
                if later is not None:
                    continue  # Premium carries on (a stacked pass, another subscription)
                _notice(session, user_id, "expiring", f"{source_id}:{ends_at.date().isoformat()}")
                reminded += 1
        return reminded

    def make_handlers(self) -> dict[str, platform.JobHandler]:
        async def reconcile(job: platform.Job) -> None:
            del job
            await self.reconcile_stripe()

        async def remind(job: platform.Job) -> None:
            del job
            await self.remind_expiring()

        return {RECONCILE_JOB: reconcile, REMINDERS_JOB: remind}

    async def transactions(
        self,
        user_id: uuid.UUID,
        *,
        cursor: str | None,
        limit: int | None,
        preferences: Sequence[str] = (),
    ) -> TransactionPage:
        """My payments, refunds and disputes, newest first (BILL-011)."""
        if self._cursors is None:
            raise AppError(ErrorCode.SERVICE_UNAVAILABLE, "Purchase history isn't available.")
        size = clamp_limit(limit)
        scope = f"billing.transactions:{user_id}"
        conditions: list[Any] = [BillingTransaction.user_id == user_id]
        if cursor:
            position = self._cursors.decode(cursor, scope=scope)
            at = datetime.fromisoformat(str(position["at"]))
            last = uuid.UUID(str(position["id"]))
            conditions.append(
                or_(
                    BillingTransaction.occurred_at < at,
                    and_(BillingTransaction.occurred_at == at, BillingTransaction.id < last),
                )
            )
        async with self._sessionmaker() as session:
            rows = list(
                await session.scalars(
                    select(BillingTransaction)
                    .where(*conditions)
                    .order_by(BillingTransaction.occurred_at.desc(), BillingTransaction.id.desc())
                    .limit(size + 1)
                )
            )
            has_more = len(rows) > size
            rows = rows[:size]
            product_ids = {r.product_id for r in rows if r.product_id is not None}
            products = {
                p.id: p
                for p in await session.scalars(select(Product).where(Product.id.in_(product_ids)))
            }
        data = []
        for row in rows:
            product = products.get(row.product_id) if row.product_id else None
            data.append(
                TransactionOut(
                    id=row.id,
                    provider=row.provider,  # type: ignore[arg-type]
                    kind=row.kind,  # type: ignore[arg-type]
                    status=row.status,  # type: ignore[arg-type]
                    amount_minor=row.amount_minor,
                    currency=row.currency,
                    reason=row.reason,
                    receipt_url=row.receipt_url,
                    product=TransactionProduct(
                        id=product.id,
                        kind=product.kind,  # type: ignore[arg-type]
                        period=product.period,
                        title=_localized(product.title, preferences),
                    )
                    if product is not None
                    else None,
                    occurred_at=row.occurred_at,
                )
            )
        next_cursor = (
            self._cursors.encode(
                {"at": rows[-1].occurred_at.isoformat(), "id": str(rows[-1].id)}, scope=scope
            )
            if has_more and rows
            else None
        )
        return TransactionPage(data=data, page=PageInfo(next_cursor=next_cursor, has_more=has_more))

    @staticmethod
    def _transition(
        subscription: Subscription,
        product: Product,
        event: StoreEvent,
        target: SubscriptionStatus,
        at: datetime,
        now: datetime,
    ) -> None:
        period = period_length(product.period)
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


@dataclass(frozen=True, slots=True)
class _StripeFacts:
    """What one webhook event is about, fetched from the API (never from the payload)."""

    event_type: str
    checkout: StripeCheckout | None = None
    subscription: StripeSubscription | None = None
    invoice: StripeInvoice | None = None
    charge: StripeCharge | None = None
    dispute: StripeDispute | None = None


async def _fetch_stripe_facts(
    stripe: StripeClient, event_type: str, object_id: str
) -> _StripeFacts:
    """Everything an event needs, read before the database transaction opens."""
    if event_type.startswith("checkout.session."):
        checkout = await stripe.get_checkout_session(object_id)
        subscription = (
            await stripe.get_subscription(checkout.subscription) if checkout.subscription else None
        )
        return _StripeFacts(event_type, checkout=checkout, subscription=subscription)
    if event_type.startswith("customer.subscription."):
        return _StripeFacts(event_type, subscription=await stripe.get_subscription(object_id))
    if event_type.startswith("invoice."):
        paid_invoice = await stripe.get_invoice(object_id)
        subscription = (
            await stripe.get_subscription(paid_invoice.subscription)
            if paid_invoice.subscription
            else None
        )
        return _StripeFacts(event_type, invoice=paid_invoice, subscription=subscription)
    if event_type == "charge.refunded":
        refunded = await stripe.get_charge(object_id)
        invoice = await stripe.get_invoice(refunded.invoice) if refunded.invoice else None
        return _StripeFacts(event_type, charge=refunded, invoice=invoice)
    if event_type.startswith("charge.dispute."):
        dispute = await stripe.get_dispute(object_id)
        charge = await stripe.get_charge(dispute.charge) if dispute.charge else None
        invoice = await stripe.get_invoice(charge.invoice) if charge and charge.invoice else None
        return _StripeFacts(event_type, dispute=dispute, charge=charge, invoice=invoice)
    return _StripeFacts(event_type)


async def _stripe_user(
    session: AsyncSession, customer: str | None, claimed: str | None
) -> uuid.UUID | None:
    """The user behind a Stripe customer; the metadata only counts for a customer we don't map
    yet (we created every customer with the user's id)."""
    if customer:
        mapped: uuid.UUID | None = await session.scalar(
            select(BillingCustomer.user_id).where(
                BillingCustomer.provider == "stripe",
                BillingCustomer.provider_customer_id == customer,
            )
        )
        if mapped is not None:
            return mapped
    try:
        return uuid.UUID(claimed) if claimed else None
    except ValueError:
        return None


async def _refuse_double_purchase(
    session: AsyncSession, user_id: uuid.UUID, product: Product, now: datetime
) -> None:
    """``409`` instead of a second charge (BILL-006): owned content, or a subscription or pass on
    top of a subscription that is still renewing. A pass may follow a pass: it starts when the
    current Premium ends."""
    if product.kind == ProductKind.NON_CONSUMABLE:
        snap = await snapshot(session, user_id, at=now)
        owned = all(snap.has_content(key) for key in product.entitlement_keys)
    else:
        owned = (
            await session.scalar(
                select(Subscription.id)
                .where(
                    Subscription.user_id == user_id,
                    Subscription.status.in_(
                        [SubscriptionStatus.ACTIVE, SubscriptionStatus.IN_GRACE_PERIOD]
                    ),
                    Subscription.auto_renew_enabled.is_(True),
                    or_(
                        Subscription.current_period_end.is_(None),
                        Subscription.current_period_end > now,
                    ),
                )
                .limit(1)
            )
            is not None
        )
    if owned:
        raise AppError(ErrorCode.CONFLICT, "You already have this.")


async def _grant_permanent(
    session: AsyncSession,
    user_id: uuid.UUID,
    product: Product,
    purchase_id: uuid.UUID,
    starts_at: datetime,
) -> None:
    for key in product.entitlement_keys:
        await session.execute(
            insert(SubscriptionEntitlement)
            .values(
                user_id=user_id,
                entitlement_key=key,
                source_type=GrantSource.PURCHASE,
                source_id=purchase_id,
                starts_at=starts_at,
            )
            .on_conflict_do_nothing()
        )


async def _grant_pass(
    session: AsyncSession,
    user_id: uuid.UUID,
    product: Product,
    purchase_id: uuid.UUID,
    paid_at: datetime,
) -> datetime:
    """Premium for the pass's period, starting when the traveller's current finite Premium ends
    (so passes stack instead of overlapping). Idempotent per purchase."""
    existing = await session.scalar(
        select(SubscriptionEntitlement.ends_at).where(
            SubscriptionEntitlement.source_type == GrantSource.PURCHASE,
            SubscriptionEntitlement.source_id == purchase_id,
        )
    )
    if existing is not None:
        return existing
    keys = list(product.entitlement_keys)
    latest = await session.scalar(
        select(func.max(SubscriptionEntitlement.ends_at)).where(
            SubscriptionEntitlement.user_id == user_id,
            SubscriptionEntitlement.entitlement_key.in_(keys),
            SubscriptionEntitlement.revoked_at.is_(None),
            SubscriptionEntitlement.ends_at > paid_at,
        )
    )
    starts = max(paid_at, latest) if latest is not None else paid_at
    ends = add_period(starts, product.period or "P1M")
    for key in keys:
        await session.execute(
            insert(SubscriptionEntitlement)
            .values(
                user_id=user_id,
                entitlement_key=key,
                source_type=GrantSource.PURCHASE,
                source_id=purchase_id,
                starts_at=starts,
                ends_at=ends,
            )
            .on_conflict_do_nothing()
        )
    await session.execute(
        update(Purchase).where(Purchase.id == purchase_id).values(expires_at=ends)
    )
    return ends


async def _grant_web_purchase(
    session: AsyncSession,
    user_id: uuid.UUID,
    product: Product,
    reference: str,
    environment: str,
    paid_at: datetime,
) -> uuid.UUID:
    """A paid one-time web purchase: the content for good, or a pass. Once per payment."""
    kind = "non_renewing" if product.kind == ProductKind.NON_RENEWING else "non_consumable"
    inserted = await session.execute(
        insert(Purchase)
        .values(
            user_id=user_id,
            provider="stripe",
            product_id=product.id,
            transaction_id=reference,
            kind=kind,
            purchased_at=paid_at,
            environment=environment,
        )
        .on_conflict_do_nothing(index_elements=[Purchase.provider, Purchase.transaction_id])
        .returning(Purchase.id)
    )
    purchase_id = inserted.scalar_one_or_none()
    if purchase_id is None:
        found = await session.scalar(
            select(Purchase.id).where(
                Purchase.provider == "stripe", Purchase.transaction_id == reference
            )
        )
        assert found is not None
        return found
    if product.kind == ProductKind.NON_RENEWING:
        await _grant_pass(session, user_id, product, purchase_id, paid_at)
    else:
        await _grant_permanent(session, user_id, product, purchase_id, paid_at)
    return purchase_id


async def _revoke_paid_by(
    session: AsyncSession,
    charge: StripeCharge,
    invoice: StripeInvoice | None,
    now: datetime,
) -> bool:
    """Revoke what a charge paid for: its invoice's subscription, or its one-time purchase."""
    revoked = False
    if invoice is not None and invoice.subscription:
        subscription = await session.scalar(
            select(Subscription)
            .where(
                Subscription.provider == "stripe",
                Subscription.original_transaction_id == invoice.subscription,
                Subscription.status != SubscriptionStatus.REVOKED,
            )
            .with_for_update()
        )
        if subscription is not None:
            subscription.status = SubscriptionStatus.REVOKED
            subscription.revoked_at = now
            subscription.last_event_at = now
            product = await session.get(Product, subscription.product_id)
            assert product is not None
            await session.flush()
            await _materialize(session, subscription, product, now=now)
            revoked = True
    if charge.payment_intent:
        purchase = await session.scalar(
            select(Purchase)
            .where(
                Purchase.provider == "stripe",
                Purchase.transaction_id == charge.payment_intent,
                Purchase.status == "verified",
            )
            .with_for_update()
        )
        if purchase is not None:
            purchase.status = "refunded"
            purchase.refunded_at = now
            await session.execute(
                update(SubscriptionEntitlement)
                .where(
                    SubscriptionEntitlement.source_type == GrantSource.PURCHASE,
                    SubscriptionEntitlement.source_id == purchase.id,
                    SubscriptionEntitlement.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            revoked = True
    return revoked


async def _duplicate_web_subscriptions(session: AsyncSession, row_id: uuid.UUID) -> list[str]:
    """Stripe ids of extra live web subscriptions next to this one; the oldest one stays."""
    row = await session.get(Subscription, row_id)
    if row is None or row.user_id is None:
        return []
    live = [SubscriptionStatus.ACTIVE, SubscriptionStatus.IN_GRACE_PERIOD]
    rows = list(
        await session.scalars(
            select(Subscription)
            .where(
                Subscription.user_id == row.user_id,
                Subscription.provider == "stripe",
                Subscription.status.in_(live),
            )
            .order_by(Subscription.created_at, Subscription.id)
        )
    )
    return [r.original_transaction_id for r in rows[1:]]


async def _record_transaction(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    provider: str,
    environment: str,
    kind: str,
    status: str,
    reference: str,
    occurred_at: datetime,
    product_id: uuid.UUID | None = None,
    subscription_id: uuid.UUID | None = None,
    purchase_id: uuid.UUID | None = None,
    amount_minor: int | None = None,
    currency: str | None = None,
    reason: str | None = None,
    receipt_url: str | None = None,
) -> None:
    """Insert or move a ledger row forward (pending → failed → succeeded; open → won or lost)."""
    receipt = receipt_url if receipt_url and receipt_url.startswith("https://") else None
    row = await session.scalar(
        select(BillingTransaction)
        .where(
            BillingTransaction.provider == provider,
            BillingTransaction.kind == kind,
            BillingTransaction.provider_reference == reference,
        )
        .with_for_update()
    )
    if row is None:
        await session.execute(
            insert(BillingTransaction)
            .values(
                user_id=user_id,
                provider=provider,
                environment=environment,
                kind=kind,
                status=status,
                provider_reference=reference,
                product_id=product_id,
                subscription_id=subscription_id,
                purchase_id=purchase_id,
                amount_minor=amount_minor,
                currency=currency,
                reason=reason,
                receipt_url=receipt,
                occurred_at=occurred_at,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    BillingTransaction.provider,
                    BillingTransaction.kind,
                    BillingTransaction.provider_reference,
                ]
            )
        )
        return
    if _STATUS_RANK[status] < _STATUS_RANK[row.status]:
        return
    row.status = status
    row.product_id = row.product_id or product_id
    row.subscription_id = row.subscription_id or subscription_id
    row.purchase_id = row.purchase_id or purchase_id
    row.amount_minor = amount_minor if amount_minor is not None else row.amount_minor
    row.currency = currency or row.currency
    row.reason = reason or row.reason
    row.receipt_url = receipt or row.receipt_url
    row.occurred_at = occurred_at if status in ("succeeded", "won", "lost") else row.occurred_at
    row.updated_at = occurred_at


def _notice(session: AsyncSession, user_id: uuid.UUID, variant: str, reference: str) -> None:
    """Tell the traveller (notifications module, via the outbox): payment_failed,
    payment_confirmed, refunded or expiring."""
    platform.record_event(
        session,
        aggregate_type="user",
        aggregate_id=user_id,
        event_type=NOTICE_EVENT,
        payload={"user_id": str(user_id), "variant": variant, "reference": reference},
    )


async def _stripe_customer(session: AsyncSession, user_id: uuid.UUID) -> str | None:
    customer: str | None = await session.scalar(
        select(BillingCustomer.provider_customer_id).where(
            BillingCustomer.user_id == user_id, BillingCustomer.provider == "stripe"
        )
    )
    return customer


async def purge_expired(session: AsyncSession) -> int:
    """Processed store notifications after 90 days (the subscription keeps the state), and
    finished Checkout sessions after 30 (the ledger keeps the payments)."""
    events = await platform.delete_batch(
        session,
        BillingEvent,
        (BillingEvent.processing_status.in_(["processed", "ignored"]))
        & (BillingEvent.received_at < platform.ago(days=90)),
    )
    checkouts = await platform.delete_batch(
        session,
        CheckoutSession,
        (CheckoutSession.status != "open") & (CheckoutSession.created_at < platform.ago(days=30)),
    )
    return events + checkouts


__all__ = [
    "BillingService",
    "Feature",
    "Quota",
    "QuotaUsage",
    "get_entitlements",
    "group_premium",
    "has",
    "quota_limit",
    "snapshot",
    "timedelta",
]


async def export_user_data(
    session: AsyncSession, user_id: uuid.UUID
) -> dict[str, list[dict[str, object]]]:
    """Personal-data export (BL-6.03; AUTH-011): what this module holds about the user."""
    from app.modules.billing.models import (
        BillingCustomer,
        BillingTransaction,
        CheckoutSession,
        Purchase,
        Subscription,
        SubscriptionEntitlement,
    )

    return {
        "billing_accounts": await platform.export_rows(
            session, BillingCustomer, BillingCustomer.user_id == user_id
        ),
        "subscriptions": await platform.export_rows(
            session, Subscription, Subscription.user_id == user_id
        ),
        "purchases": await platform.export_rows(session, Purchase, Purchase.user_id == user_id),
        "entitlements": await platform.export_rows(
            session, SubscriptionEntitlement, SubscriptionEntitlement.user_id == user_id
        ),
        "transactions": await platform.export_rows(
            session, BillingTransaction, BillingTransaction.user_id == user_id
        ),
        "checkout_sessions": await platform.export_rows(
            session, CheckoutSession, CheckoutSession.user_id == user_id
        ),
    }


# ─────────────────────────── staff grants (BILL-009) ───────────────────────────

MAX_GRANT = timedelta(days=366)


def _grant_out(row: SubscriptionEntitlement) -> EntitlementGrantOut:
    return EntitlementGrantOut(
        id=row.id,
        user_id=row.user_id,
        entitlement_key=row.entitlement_key,
        source_type=row.source_type,  # type: ignore[arg-type]
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        revoked_at=row.revoked_at,
        created_at=row.created_at,
    )


async def grant_entitlement(
    session: AsyncSession, user_id: uuid.UUID, *, key: str, ends_at: datetime, now: datetime
) -> EntitlementGrantOut:
    """A time-limited promotional grant (the admin module audits it in the same transaction)."""
    if ends_at <= now or ends_at > now + MAX_GRANT:
        raise AppError(
            ErrorCode.VALIDATION_FAILED,
            "A grant ends within the next year.",
            errors=[
                FieldError(
                    field="/ends_at", code="range", message="Pick an end date within a year."
                )
            ],
        )
    grant_id = uuid.uuid4()
    row = SubscriptionEntitlement(
        id=grant_id,
        user_id=user_id,
        entitlement_key=key,
        source_type=GrantSource.ADMIN_GRANT,
        source_id=grant_id,
        starts_at=now,
        ends_at=ends_at,
        created_at=now,
    )
    session.add(row)
    await session.flush()
    return _grant_out(row)


async def staff_grants(session: AsyncSession, user_id: uuid.UUID) -> list[EntitlementGrantOut]:
    rows = await session.scalars(
        select(SubscriptionEntitlement)
        .where(
            SubscriptionEntitlement.user_id == user_id,
            SubscriptionEntitlement.source_type.in_((GrantSource.PROMO, GrantSource.ADMIN_GRANT)),
        )
        .order_by(SubscriptionEntitlement.created_at.desc())
    )
    return [_grant_out(r) for r in rows]


async def revoke_staff_grant(
    session: AsyncSession, grant_id: uuid.UUID, *, now: datetime
) -> EntitlementGrantOut:
    row = await session.get(SubscriptionEntitlement, grant_id, with_for_update=True)
    if row is None or row.source_type not in (GrantSource.PROMO, GrantSource.ADMIN_GRANT):
        raise AppError(ErrorCode.NOT_FOUND, "Grant not found.")
    if row.revoked_at is None:
        row.revoked_at = now
        await session.flush()
    return _grant_out(row)


# ─────────────────────────── product configuration (ADM-005) ───────────────────────────


def _admin_product(row: Product) -> AdminProductOut:
    return AdminProductOut(
        id=row.id,
        sku=row.sku,
        platform=row.platform,  # type: ignore[arg-type]
        kind=row.kind,  # type: ignore[arg-type]
        plan_key=row.plan_key,  # type: ignore[arg-type]
        period=row.period,
        entitlement_keys=list(row.entitlement_keys or []),
        active=row.active,
        title=dict(row.title or {}),
        description=dict(row.description or {}),
        sort_order=row.sort_order,
    )


async def admin_products(session: AsyncSession) -> list[AdminProductOut]:
    rows = await session.scalars(
        select(Product).order_by(Product.platform, Product.sort_order, Product.sku)
    )
    return [_admin_product(r) for r in rows]


async def create_product(session: AsyncSession, request: CreateProductRequest) -> AdminProductOut:
    """Subscriptions and passes are Premium for a period (BILL-010); content purchases have
    neither a plan nor a period. Prices live with the store or Stripe (the SKU)."""
    timed = request.kind in ("auto_renewable", "non_renewing")
    if timed != (request.plan_key is not None) or timed != (request.period is not None):
        raise AppError(
            ErrorCode.VALIDATION_FAILED,
            "Subscriptions and passes need a plan and a period; content purchases have neither.",
            errors=[FieldError(field="/period", code="invalid", message="Check plan and period.")],
        )
    exists = await session.scalar(
        select(Product.id).where(Product.platform == request.platform, Product.sku == request.sku)
    )
    if exists is not None:
        raise AppError(ErrorCode.CONFLICT, "That SKU already exists on this platform.")
    row = Product(
        sku=request.sku,
        platform=request.platform,
        kind=request.kind,
        plan_key=request.plan_key,
        period=request.period,
        entitlement_keys=list(dict.fromkeys(request.entitlement_keys)),
        active=True,
        title=dict(request.title),
        description=dict(request.description),
        sort_order=request.sort_order,
    )
    session.add(row)
    await session.flush()
    return _admin_product(row)


def _days(period: timedelta) -> int:
    return period // timedelta(days=1)


async def billing_policy(session: AsyncSession) -> BillingPolicyOut:
    row = await session.get(EntitlementPolicyOverride, 1)
    policy = _policy_from(row)
    return BillingPolicyOut(
        quotas=[
            PolicyQuotaOut(
                key=quota.value,
                period=default.period.value,
                free=policy.quotas[quota].free,
                premium=policy.quotas[quota].premium,
                default_free=default.free,
                default_premium=default.premium,
            )
            for quota, default in DEFAULT_QUOTAS.items()
        ],
        group_admin_grace_days=_days(policy.group_admin_grace_period),
        default_group_admin_grace_days=_days(DEFAULT_POLICY.group_admin_grace_period),
        version=row.version if row is not None else 0,
        updated_at=row.updated_at if row is not None else None,
        updated_by=row.updated_by if row is not None else None,
    )


async def update_billing_policy(
    session: AsyncSession,
    request: UpdateBillingPolicyRequest,
    *,
    staff_id: uuid.UUID,
    now: datetime,
) -> tuple[BillingPolicyOut, BillingPolicyOut]:
    """Replace the overrides (optimistic: ``version`` must match). Returns (before, after)."""
    for key, limits in request.quotas.items():
        if limits.free > limits.premium:
            message = "The free limit cannot be higher than the premium limit."
            raise AppError(
                ErrorCode.VALIDATION_FAILED,
                message,
                errors=[FieldError(field=f"/quotas/{key}", code="invalid", message=message)],
            )
    row = await session.get(EntitlementPolicyOverride, 1, with_for_update=True)
    before = await billing_policy(session)
    if request.version != before.version:
        raise AppError(
            ErrorCode.CONFLICT, "The policy changed since you loaded it. Reload and try again."
        )
    overrides: dict[str, Any] = {
        key: {"free": limits.free, "premium": limits.premium}
        for key, limits in request.quotas.items()
    }
    if row is None:
        row = EntitlementPolicyOverride(id=1, version=0)
        session.add(row)
    row.quotas = overrides
    row.group_admin_grace_days = request.group_admin_grace_days
    row.version = before.version + 1
    row.updated_at = now
    row.updated_by = staff_id
    try:
        await session.flush()
    except IntegrityError as exc:  # another first save won the singleton row
        raise AppError(
            ErrorCode.CONFLICT, "The policy changed since you loaded it. Reload and try again."
        ) from exc
    return before, await billing_policy(session)


async def update_product(
    session: AsyncSession, product_id: uuid.UUID, request: UpdateProductRequest
) -> AdminProductOut:
    row = await session.get(Product, product_id, with_for_update=True)
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND, "Product not found.")
    if request.active is not None:
        row.active = request.active
    if request.entitlement_keys is not None:
        row.entitlement_keys = list(dict.fromkeys(request.entitlement_keys))
    if request.title is not None:
        row.title = dict(request.title)
    if request.description is not None:
        row.description = dict(request.description)
    if request.sort_order is not None:
        row.sort_order = request.sort_order
    await session.flush()
    return _admin_product(row)
