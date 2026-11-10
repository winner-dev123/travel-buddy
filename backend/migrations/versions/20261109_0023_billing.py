"""Billing: products, subscriptions, purchases, materialized grants, store events (BL-3.01/3.02).

Seeds the premium subscription products for iOS and Android (one subscription group, monthly and
annual). The SKUs must match App Store Connect and Play Console; prices live in the stores.

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _check(name: str, column: str, values: Sequence[str]) -> sa.CheckConstraint:
    """``op.f``: ``name`` is final, so the naming convention does not prefix it again."""
    allowed = ", ".join(f"'{v}'" for v in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=op.f(name))


def _ts(name: str, *, nullable: bool = True, now: bool = False) -> sa.Column[sa.DateTime]:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()") if now else None,
        nullable=nullable,
    )


def _fk(table: str, column: str, referred: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], [f"{referred}.id"], name=f"fk_{table}__{column}__{referred}", ondelete=ondelete
    )


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("sku", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("plan_key", sa.Text(), nullable=True),
        sa.Column("period", sa.Text(), nullable=True),
        sa.Column(
            "entitlement_keys",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("grants_content", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        _check("ck_products__platform_enum", "platform", ["ios", "android", "web"]),
        _check("ck_products__kind_enum", "kind", ["auto_renewable", "non_consumable"]),
        _check("ck_products__period_enum", "period", ["P1M", "P1Y"]),
        sa.PrimaryKeyConstraint("id", name="pk_products"),
        sa.UniqueConstraint("platform", "sku", name="uq_products__platform_sku"),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("original_transaction_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "auto_renew_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        _ts("current_period_start", nullable=False),
        _ts("current_period_end"),
        _ts("grace_period_ends_at"),
        _ts("cancelled_at"),
        _ts("expired_at"),
        _ts("revoked_at"),
        sa.Column("environment", sa.Text(), server_default=sa.text("'production'"), nullable=False),
        _ts("last_event_at"),
        _ts("created_at", nullable=False, now=True),
        _ts("updated_at", nullable=False, now=True),
        _check("ck_subscriptions__provider_enum", "provider", ["apple", "google", "stripe", "dev"]),
        _check(
            "ck_subscriptions__status_enum",
            "status",
            ["active", "in_grace_period", "in_billing_retry", "paused", "expired", "revoked"],
        ),
        _check("ck_subscriptions__environment_enum", "environment", ["production", "sandbox"]),
        _fk("subscriptions", "user_id", "users", "RESTRICT"),
        _fk("subscriptions", "product_id", "products", "RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_subscriptions"),
        sa.UniqueConstraint(
            "provider",
            "original_transaction_id",
            name="uq_subscriptions__provider_original_transaction_id",
        ),
    )
    op.create_index("ix_subscriptions__user_id", "subscriptions", ["user_id"])

    op.create_table(
        "purchases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        _ts("purchased_at", nullable=False),
        _ts("refunded_at"),
        sa.Column("environment", sa.Text(), server_default=sa.text("'production'"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'verified'"), nullable=False),
        _ts("created_at", nullable=False, now=True),
        _check("ck_purchases__provider_enum", "provider", ["apple", "google", "stripe", "dev"]),
        _check(
            "ck_purchases__kind_enum",
            "kind",
            ["non_consumable", "subscription_purchase", "renewal"],
        ),
        _check("ck_purchases__status_enum", "status", ["verified", "refunded", "revoked"]),
        _check("ck_purchases__environment_enum", "environment", ["production", "sandbox"]),
        _fk("purchases", "user_id", "users", "RESTRICT"),
        _fk("purchases", "product_id", "products", "RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_purchases"),
        sa.UniqueConstraint(
            "provider", "transaction_id", name="uq_purchases__provider_transaction_id"
        ),
    )
    op.create_index("ix_purchases__user_id", "purchases", ["user_id"])

    op.create_table(
        "subscription_entitlements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("entitlement_key", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        _ts("starts_at", nullable=False),
        _ts("ends_at"),
        _ts("revoked_at"),
        _ts("created_at", nullable=False, now=True),
        _check(
            "ck_subscription_entitlements__source_type_enum",
            "source_type",
            ["subscription", "purchase", "promo", "admin_grant"],
        ),
        _fk("subscription_entitlements", "user_id", "users", "RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_subscription_entitlements"),
        sa.UniqueConstraint(
            "source_type",
            "source_id",
            "entitlement_key",
            name="uq_subscription_entitlements__source",
        ),
    )
    op.create_index(
        "ix_subscription_entitlements__active_user",
        "subscription_entitlements",
        ["user_id", "entitlement_key"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "billing_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_event_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("subtype", sa.Text(), nullable=True),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
        _ts("signed_date"),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        _ts("received_at", nullable=False, now=True),
        _ts("processed_at"),
        sa.Column(
            "processing_status", sa.Text(), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        _check(
            "ck_billing_events__provider_enum", "provider", ["apple", "google", "stripe", "dev"]
        ),
        _check(
            "ck_billing_events__processing_enum",
            "processing_status",
            ["pending", "processed", "ignored", "failed"],
        ),
        _fk("billing_events", "subscription_id", "subscriptions", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_billing_events"),
        sa.UniqueConstraint(
            "provider", "provider_event_id", name="uq_billing_events__provider_provider_event_id"
        ),
    )

    op.execute(
        """
        INSERT INTO products (id, sku, platform, kind, plan_key, period, entitlement_keys)
        VALUES
          (gen_random_uuid(), 'com.travelbuddy.premium.monthly', 'ios', 'auto_renewable',
           'premium', 'P1M', ARRAY['premium']),
          (gen_random_uuid(), 'com.travelbuddy.premium.annual', 'ios', 'auto_renewable',
           'premium', 'P1Y', ARRAY['premium']),
          (gen_random_uuid(), 'premium_monthly', 'android', 'auto_renewable',
           'premium', 'P1M', ARRAY['premium']),
          (gen_random_uuid(), 'premium_annual', 'android', 'auto_renewable',
           'premium', 'P1Y', ARRAY['premium'])
        """
    )


def downgrade() -> None:
    for table in (
        "billing_events",
        "subscription_entitlements",
        "purchases",
        "subscriptions",
        "products",
    ):
        op.drop_table(table)
