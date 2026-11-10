"""Billing tables (docs/04 §11). Private to the billing module; only ``subscription_entitlements``
feeds the evaluator."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_check
from app.core.ids import uuid7
from app.modules.billing.domain import ProductKind, ProviderName, SubscriptionStatus
from app.modules.billing.entitlements import GrantSource


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("platform", "sku"),
        enum_check("platform", ("ios", "android", "web"), "platform_enum"),
        enum_check("kind", ProductKind, "kind_enum"),
        enum_check("period", ("P1M", "P1Y"), "period_enum"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    sku: Mapped[str] = mapped_column(Text)
    platform: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    plan_key: Mapped[str | None] = mapped_column(Text)
    period: Mapped[str | None] = mapped_column(Text)
    entitlement_keys: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    grants_content: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("provider", "original_transaction_id"),
        enum_check("provider", ProviderName, "provider_enum"),
        enum_check("status", SubscriptionStatus, "status_enum"),
        enum_check("environment", ("production", "sandbox"), "environment_enum"),
        Index("ix_subscriptions__user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    # SET NULL: billing records outlive the account for legal retention, pseudonymized.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(Text)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    original_transaction_id: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    auto_renew_enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    grace_period_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    environment: Mapped[str] = mapped_column(Text, server_default=text("'production'"))
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Purchase(Base):
    __tablename__ = "purchases"
    __table_args__ = (
        UniqueConstraint("provider", "transaction_id"),
        enum_check("provider", ProviderName, "provider_enum"),
        enum_check("kind", ("non_consumable", "subscription_purchase", "renewal"), "kind_enum"),
        enum_check("status", ("verified", "refunded", "revoked"), "status_enum"),
        enum_check("environment", ("production", "sandbox"), "environment_enum"),
        Index("ix_purchases__user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    # SET NULL: billing records outlive the account for legal retention, pseudonymized.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    provider: Mapped[str] = mapped_column(Text)
    product_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    transaction_id: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    purchased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    environment: Mapped[str] = mapped_column(Text, server_default=text("'production'"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'verified'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SubscriptionEntitlement(Base):
    """Materialized grants: the only table the evaluator reads (docs/07 §1)."""

    __tablename__ = "subscription_entitlements"
    __table_args__ = (
        # Explicit name: the conventional one is longer than 63 characters.
        UniqueConstraint(
            "source_type",
            "source_id",
            "entitlement_key",
            name="uq_subscription_entitlements__source",
        ),
        enum_check("source_type", GrantSource, "source_type_enum"),
        Index(
            "ix_subscription_entitlements__active_user",
            "user_id",
            "entitlement_key",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    # SET NULL: billing records outlive the account for legal retention, pseudonymized.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    entitlement_key: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(Text)
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BillingEvent(Base):
    """Store notifications inbox, idempotent per provider event (docs/04 §11)."""

    __tablename__ = "billing_events"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id"),
        enum_check("provider", ProviderName, "provider_enum"),
        enum_check(
            "processing_status", ("pending", "processed", "ignored", "failed"), "processing_enum"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    provider: Mapped[str] = mapped_column(Text)
    provider_event_id: Mapped[str] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(Text)
    subtype: Mapped[str | None] = mapped_column(Text)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("subscriptions.id", ondelete="SET NULL")
    )
    signed_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class BillingCustomer(Base):
    """A user's Stripe customer, for Checkout and the Customer Portal (ADR-0012). Card data is
    never stored (hosted Checkout)."""

    __tablename__ = "billing_customers"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "provider"),
        UniqueConstraint("provider", "provider_customer_id"),
        enum_check("provider", ("stripe",), "provider_enum"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, server_default=text("'stripe'"))
    provider_customer_id: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EntitlementPolicyOverride(Base):
    """Runtime overrides of the entitlement policy defaults (docs/07 section 3; BL-6.02). At most
    one row; no row, or a quota missing from ``quotas``, means the code default."""

    __tablename__ = "entitlement_policy_overrides"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    # {"ai.itinerary_generations": {"free": 5, "premium": 60}, ...}
    quotas: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    group_admin_grace_days: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # staff; no FK, like audit actors
