"""Entitlements response model (contract ``Entitlements``; docs/07 section 7)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


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


class ProductOut(_Model):
    """Contract ``Product`` (prices come from the store or Stripe, never from here)."""

    id: uuid.UUID
    sku: str
    platform: Literal["ios", "android", "web"]
    provider: Literal["apple", "google", "stripe", "dev"]
    kind: Literal["auto_renewable", "non_consumable"]
    plan_key: Literal["premium"] | None
    period: Literal["P1M", "P1Y"] | None
    entitlement_keys: list[str]
    grants_content: list[GrantedContent] = Field(default_factory=list)


class ProductList(_Model):
    data: list[ProductOut]


class PurchaseOut(_Model):
    id: uuid.UUID
    provider: Literal["apple", "google", "stripe", "dev"]
    product_sku: str
    kind: Literal["non_consumable", "subscription_purchase", "renewal"]
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


class AdminProductOut(BaseModel):
    """Contract ``AdminProduct`` (ADM-005)."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    sku: str
    platform: Literal["ios", "android", "web"]
    kind: Literal["auto_renewable", "non_consumable"]
    plan_key: Literal["premium"] | None
    period: Literal["P1M", "P1Y"] | None
    entitlement_keys: list[str]
    active: bool


class AdminProductList(BaseModel):
    model_config = ConfigDict(frozen=True)

    data: list[AdminProductOut]


class CreateProductRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku: str = Field(min_length=3, max_length=200)
    platform: Literal["ios", "android", "web"]
    kind: Literal["auto_renewable", "non_consumable"]
    plan_key: Literal["premium"] | None = None
    period: Literal["P1M", "P1Y"] | None = None
    entitlement_keys: list[EntitlementKey] = Field(min_length=1, max_length=10)


class UpdateProductRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool | None = None
    entitlement_keys: list[EntitlementKey] | None = Field(default=None, min_length=1, max_length=10)


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
