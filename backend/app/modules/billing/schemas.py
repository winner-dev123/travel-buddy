"""Entitlements response model (contract ``Entitlements``; docs/07 section 7)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.core.i18n import SUPPORTED_LOCALES
from app.core.pagination import PageInfo
from app.modules.billing.domain import PERIOD_PATTERN

ProductKindName = Literal["auto_renewable", "non_renewing", "non_consumable"]
Period = Annotated[str, StringConstraints(pattern=PERIOD_PATTERN)]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)


class QuotaStatusOut(_Model):
    limit: int
    used: int
    resets_at: datetime | None


class EntitlementFeatures(_Model):
    groups_create: bool = Field(alias="groups.create")
    challenges_create: bool = Field(alias="challenges.create")
    guides_premium: bool = Field(alias="guides.premium")
    audio_tours_premium: bool = Field(alias="audio_tours.premium")
    ai_trip_replan: bool = Field(alias="ai.trip_replan")


class EntitlementQuotas(_Model):
    ai_itinerary_generations: QuotaStatusOut = Field(alias="ai.itinerary_generations")
    ai_trip_replans: QuotaStatusOut = Field(alias="ai.trip_replans")
    offline_packages: QuotaStatusOut = Field(alias="offline.packages")
    groups_owned: QuotaStatusOut = Field(alias="groups.owned")


class ActiveSubscription(_Model):
    provider: Literal["apple", "google", "stripe", "dev"]
    product_id: uuid.UUID
    auto_renew: bool
    management: Literal["app_store", "google_play", "stripe_portal"]


class Entitlements(_Model):
    plan: Literal["free", "premium"]
    status: Literal[
        "none", "active", "in_grace_period", "in_billing_retry", "paused", "expired", "revoked"
    ]
    premium_until: datetime | None
    store_grace_until: datetime | None
    features: EntitlementFeatures
    quotas: EntitlementQuotas
    active_subscription: ActiveSubscription | None = None


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GrantedContent(_Model):
    type: Literal["guide", "audio_tour", "offline_package"]
    id: uuid.UUID


class ProductPrice(_Model):
    """Contract ``ProductPrice``: what Stripe charges for a web offer. Store apps show the store's
    own localized price instead (never this one)."""

    amount_minor: int
    currency: str
    recurring: bool


class ProductOut(_Model):
    """Contract ``Product`` (prices come from the store or Stripe, never from here)."""

    id: uuid.UUID
    sku: str
    platform: Literal["ios", "android", "web"]
    provider: Literal["apple", "google", "stripe", "dev"]
    kind: ProductKindName
    plan_key: Literal["premium"] | None
    # ISO 8601: renewal period of a subscription, validity of a pass (BILL-010).
    period: str | None
    entitlement_keys: list[str]
    grants_content: list[GrantedContent] = Field(default_factory=list)
    title: str | None = None
    description: str | None = None
    price: ProductPrice | None = None


class ProductList(_Model):
    data: list[ProductOut]


class PurchaseOut(_Model):
    id: uuid.UUID
    provider: Literal["apple", "google", "stripe", "dev"]
    product_sku: str
    kind: Literal["non_consumable", "non_renewing", "subscription_purchase", "renewal"]
    status: Literal["verified", "refunded", "revoked"]
    purchased_at: datetime


class VerifyPurchaseResult(_Model):
    purchase: PurchaseOut
    entitlements: Entitlements


class AppleVerifyRequest(_Request):
    provider: Literal["apple"]
    signed_transaction: str = Field(min_length=20, max_length=16384)


class GoogleVerifyRequest(_Request):
    provider: Literal["google"]
    product_sku: str = Field(max_length=200)
    purchase_token: str = Field(min_length=10, max_length=4096)
    package_name: str = Field(max_length=200)


class GooglePurchaseRef(_Request):
    product_sku: str = Field(max_length=200)
    purchase_token: str = Field(min_length=10, max_length=4096)


class AppleRestoreRequest(_Request):
    provider: Literal["apple"]
    signed_transactions: list[str] = Field(min_length=1, max_length=100)


class GoogleRestoreRequest(_Request):
    provider: Literal["google"]
    package_name: str = Field(max_length=200)
    purchases: list[GooglePurchaseRef] = Field(min_length=1, max_length=100)


class DevBillingEventRequest(_Request):
    """Development and tests only: simulate a store notification for a dev subscription."""

    original_transaction_id: str = Field(min_length=1, max_length=200)
    event: Literal[
        "renewed",
        "grace",
        "billing_retry",
        "recovered",
        "paused",
        "resumed",
        "auto_renew_off",
        "auto_renew_on",
        "expired",
        "refunded",
    ]
    event_id: str | None = Field(default=None, max_length=200)
    signed_date: datetime | None = None


class EntitlementGrantOut(BaseModel):
    """Contract ``EntitlementGrant`` (BILL-009)."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    user_id: uuid.UUID | None
    entitlement_key: str
    source_type: Literal["promo", "admin_grant"]
    starts_at: datetime
    ends_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class EntitlementGrantList(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: list[EntitlementGrantOut]


class GrantEntitlementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entitlement_key: str = Field(pattern=r"^(premium|content:[a-z_]+:[a-z0-9_-]{1,60})$")
    ends_at: datetime
    reason: str = Field(min_length=10, max_length=500)


EntitlementKey = Annotated[
    str, StringConstraints(pattern=r"^(premium|content:[a-z_]+:[a-z0-9_-]{1,60})$")
]


LocalizedText = Annotated[dict[str, str], Field(max_length=len(SUPPORTED_LOCALES))]


def _check_localized(value: dict[str, str] | None, limit: int) -> dict[str, str] | None:
    if value is None:
        return None
    for locale, text in value.items():
        if locale not in SUPPORTED_LOCALES:
            raise ValueError(f"unsupported locale {locale!r}")
        if not text.strip() or len(text) > limit:
            raise ValueError(f"{locale}: 1 to {limit} characters")
    return {locale: text.strip() for locale, text in value.items()}


class AdminProductOut(BaseModel):
    """Contract ``AdminProduct`` (ADM-005, BILL-010)."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    sku: str
    platform: Literal["ios", "android", "web"]
    kind: ProductKindName
    plan_key: Literal["premium"] | None
    period: str | None
    entitlement_keys: list[str]
    active: bool
    title: dict[str, str] = Field(default_factory=dict)
    description: dict[str, str] = Field(default_factory=dict)
    sort_order: int = 0


class AdminProductList(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: list[AdminProductOut]


class CreateProductRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=3, max_length=200)
    platform: Literal["ios", "android", "web"]
    kind: ProductKindName
    plan_key: Literal["premium"] | None = None
    period: Period | None = None
    entitlement_keys: list[EntitlementKey] = Field(min_length=1, max_length=10)
    title: LocalizedText = Field(default_factory=dict)
    description: LocalizedText = Field(default_factory=dict)
    sort_order: int = Field(default=0, ge=0, le=1000)

    @field_validator("title")
    @classmethod
    def _title(cls, value: dict[str, str]) -> dict[str, str]:
        return _check_localized(value, 80) or {}

    @field_validator("description")
    @classmethod
    def _description(cls, value: dict[str, str]) -> dict[str, str]:
        return _check_localized(value, 300) or {}


class UpdateProductRequest(BaseModel):
    """Prices and periods live with the store or Stripe: changing them means a new product."""

    model_config = ConfigDict(extra="forbid")

    active: bool | None = None
    entitlement_keys: list[EntitlementKey] | None = Field(default=None, min_length=1, max_length=10)
    title: LocalizedText | None = None
    description: LocalizedText | None = None
    sort_order: int | None = Field(default=None, ge=0, le=1000)

    @field_validator("title")
    @classmethod
    def _title(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return _check_localized(value, 80)

    @field_validator("description")
    @classmethod
    def _description(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return _check_localized(value, 300)


class TransactionProduct(_Model):
    id: uuid.UUID
    kind: ProductKindName
    period: str | None
    title: str | None


class TransactionOut(_Model):
    """Contract ``BillingTransaction`` (BILL-011): one payment, refund or dispute of mine."""

    id: uuid.UUID
    provider: Literal["apple", "google", "stripe", "dev"]
    kind: Literal["payment", "refund", "dispute"]
    status: Literal["pending", "succeeded", "failed", "open", "won", "lost"]
    amount_minor: int | None
    currency: str | None
    reason: str | None
    receipt_url: str | None
    product: TransactionProduct | None
    occurred_at: datetime


class TransactionPage(_Model):
    data: list[TransactionOut]
    page: PageInfo


class AdminTransactionOut(_Model):
    """Contract ``AdminBillingTransaction``: one ledger row for staff (no card data)."""

    id: uuid.UUID
    user_id: uuid.UUID | None
    provider: Literal["apple", "google", "stripe", "dev"]
    environment: Literal["production", "sandbox"]
    kind: Literal["payment", "refund", "dispute"]
    status: Literal["pending", "succeeded", "failed", "open", "won", "lost"]
    amount_minor: int | None
    currency: str | None
    reason: str | None
    provider_reference: str
    product: TransactionProduct | None
    occurred_at: datetime


class AdminTransactionPage(_Model):
    data: list[AdminTransactionOut]
    page: PageInfo


class RevenueTotal(_Model):
    """Payments minus refunds in one currency and environment (staff overview)."""

    currency: str
    environment: Literal["production", "sandbox"]
    amount_minor: int


QuotaKey = Literal[
    "ai.itinerary_generations", "ai.trip_replans", "offline.packages", "groups.owned"
]
QuotaValue = Annotated[int, Field(ge=0, le=100_000)]


class QuotaLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    free: QuotaValue
    premium: QuotaValue


class PolicyQuotaOut(BaseModel):
    """Contract ``BillingPolicy.quotas[]``: the value in force and the code default."""

    model_config = ConfigDict(frozen=True)

    key: QuotaKey
    period: Literal["monthly", "none"]
    free: int
    premium: int
    default_free: int
    default_premium: int


class BillingPolicyOut(BaseModel):
    """Contract ``BillingPolicy`` (BL-6.02)."""

    model_config = ConfigDict(frozen=True)

    quotas: list[PolicyQuotaOut]
    group_admin_grace_days: int
    default_group_admin_grace_days: int
    version: int
    updated_at: datetime | None
    updated_by: uuid.UUID | None


class UpdateBillingPolicyRequest(BaseModel):
    """Replaces every override: quotas left out, and a null grace, go back to the defaults."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=0)
    quotas: dict[QuotaKey, QuotaLimits] = Field(default_factory=dict)
    group_admin_grace_days: int | None = Field(default=None, ge=0, le=90)
