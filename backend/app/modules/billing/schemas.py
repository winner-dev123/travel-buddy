"""Entitlements response model (contract ``Entitlements``; docs/07 section 7)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
