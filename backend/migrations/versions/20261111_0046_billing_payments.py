"""Configurable offers, passes, the money ledger and checkout sessions (BILL-010..012).

* ``products``: any ISO 8601 period (days, weeks, months, years), passes that never renew
  (``non_renewing``), and per-locale titles, descriptions and an order for the plan list.
* ``purchases``: passes, with the moment their Premium ends.
* ``billing_transactions``: one row per payment, refund or dispute.
* ``billing_checkout_sessions``: open hosted Checkout sessions, handed out again instead of a
  second payment.

Revision ID: 0046
Revises: 0045
Create Date: 2026-11-11
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0046"
down_revision: str | None = "0045"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERIOD_PATTERN = "^P[1-9][0-9]{0,2}[DWMY]$"

_MONTHLY = {
    "title": {
        "en": "Premium monthly",
        "es": "Premium mensual",
        "pt-BR": "Premium mensal",
        "fr": "Premium mensuel",
        "de": "Premium monatlich",
    },
    "description": {
        "en": "Every Premium feature. Renews monthly; cancel anytime.",
        "es": "Todas las funciones Premium. Se renueva cada mes; cancela cuando quieras.",
        "pt-BR": "Todos os recursos Premium. Renova todo mês; cancele quando quiser.",
        "fr": "Toutes les fonctions Premium. Renouvelé chaque mois, résiliable à tout moment.",
        "de": "Alle Premium-Funktionen. Verlängert sich monatlich, jederzeit kündbar.",
    },
}
_ANNUAL = {
    "title": {
        "en": "Premium annual",
        "es": "Premium anual",
        "pt-BR": "Premium anual",
        "fr": "Premium annuel",
        "de": "Premium jährlich",
    },
    "description": {
        "en": "Every Premium feature for a year. Renews yearly; cancel anytime.",
        "es": "Todas las funciones Premium durante un año. Se renueva cada año; cancela cuando "
        "quieras.",
        "pt-BR": "Todos os recursos Premium por um ano. Renova todo ano; cancele quando quiser.",
        "fr": "Toutes les fonctions Premium pendant un an. Renouvelé chaque année, résiliable à "
        "tout moment.",
        "de": "Alle Premium-Funktionen für ein Jahr. Verlängert sich jährlich, jederzeit kündbar.",
    },
}


def _check(name: str, column: str, values: Sequence[str]) -> sa.CheckConstraint:
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


def _jsonb(name: str) -> sa.Column[dict[str, str]]:
    return sa.Column(
        name,
        postgresql.JSONB(astext_type=sa.Text()),
        server_default=sa.text("'{}'::jsonb"),
        nullable=False,
    )


def upgrade() -> None:
    product_kinds = _check(
        "ck_products__kind_enum", "kind", ["auto_renewable", "non_renewing", "non_consumable"]
    )
    purchase_kinds = _check(
        "ck_purchases__kind_enum",
        "kind",
        ["non_consumable", "non_renewing", "subscription_purchase", "renewal"],
    )
    op.execute("ALTER TABLE products DROP CONSTRAINT ck_products__kind_enum")
    op.execute(
        f"ALTER TABLE products ADD CONSTRAINT ck_products__kind_enum CHECK ({product_kinds.sqltext})"
    )
    op.execute("ALTER TABLE products DROP CONSTRAINT ck_products__period_enum")
    op.execute(
        "ALTER TABLE products ADD CONSTRAINT ck_products__period_format "
        f"CHECK (period IS NULL OR period ~ '{PERIOD_PATTERN}')"
    )
    op.add_column("products", _jsonb("title"))
    op.add_column("products", _jsonb("description"))
    op.add_column(
        "products",
        sa.Column("sort_order", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
    )
    for skus, copy, order in (
        (("com.travelbuddy.premium.monthly", "premium_monthly"), _MONTHLY, 10),
        (("com.travelbuddy.premium.annual", "premium_annual"), _ANNUAL, 20),
    ):
        op.execute(
            sa.text(
                "UPDATE products SET title = CAST(:title AS jsonb), "
                "description = CAST(:description AS jsonb), sort_order = :order "
                "WHERE sku IN :skus"
            )
            .bindparams(sa.bindparam("skus", expanding=True))
            .bindparams(
                title=json.dumps(copy["title"], ensure_ascii=False),
                description=json.dumps(copy["description"], ensure_ascii=False),
                order=order,
                skus=list(skus),
            )
        )

    op.execute("ALTER TABLE purchases DROP CONSTRAINT ck_purchases__kind_enum")
    op.execute(
        f"ALTER TABLE purchases ADD CONSTRAINT ck_purchases__kind_enum CHECK ({purchase_kinds.sqltext})"
    )
    op.add_column("purchases", _ts("expires_at"))

    op.create_table(
        "billing_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("environment", sa.Text(), server_default=sa.text("'production'"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("provider_reference", sa.Text(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
        sa.Column("purchase_id", sa.Uuid(), nullable=True),
        sa.Column("amount_minor", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("receipt_url", sa.Text(), nullable=True),
        _ts("occurred_at", nullable=False),
        _ts("created_at", nullable=False, now=True),
        _ts("updated_at", nullable=False, now=True),
        _check(
            "ck_billing_transactions__provider_enum",
            "provider",
            ["apple", "google", "stripe", "dev"],
        ),
        _check("ck_billing_transactions__kind_enum", "kind", ["payment", "refund", "dispute"]),
        _check(
            "ck_billing_transactions__status_enum",
            "status",
            ["pending", "succeeded", "failed", "open", "won", "lost"],
        ),
        _check(
            "ck_billing_transactions__environment_enum", "environment", ["production", "sandbox"]
        ),
        sa.CheckConstraint(
            "amount_minor IS NULL OR amount_minor >= 0",
            name=op.f("ck_billing_transactions__amount_positive"),
        ),
        sa.CheckConstraint(
            "currency IS NULL OR currency ~ '^[A-Z]{3}$'",
            name=op.f("ck_billing_transactions__currency_format"),
        ),
        sa.CheckConstraint(
            "receipt_url IS NULL OR receipt_url LIKE 'https://%'",
            name=op.f("ck_billing_transactions__receipt_https"),
        ),
        _fk("billing_transactions", "user_id", "users", "SET NULL"),
        _fk("billing_transactions", "product_id", "products", "RESTRICT"),
        _fk("billing_transactions", "subscription_id", "subscriptions", "SET NULL"),
        _fk("billing_transactions", "purchase_id", "purchases", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_billing_transactions"),
        sa.UniqueConstraint(
            "provider",
            "kind",
            "provider_reference",
            name="uq_billing_transactions__provider_kind_provider_reference",
        ),
    )
    op.create_index(
        "ix_billing_transactions__user_occurred",
        "billing_transactions",
        ["user_id", "occurred_at"],
    )

    op.create_table(
        "billing_checkout_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.Text(), server_default=sa.text("'stripe'"), nullable=False),
        sa.Column("provider_session_id", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'open'"), nullable=False),
        _ts("expires_at", nullable=False),
        _ts("completed_at"),
        _ts("created_at", nullable=False, now=True),
        _check("ck_billing_checkout_sessions__provider_enum", "provider", ["stripe"]),
        _check(
            "ck_billing_checkout_sessions__status_enum", "status", ["open", "complete", "expired"]
        ),
        sa.CheckConstraint(
            "url LIKE 'https://%'", name=op.f("ck_billing_checkout_sessions__url_https")
        ),
        _fk("billing_checkout_sessions", "user_id", "users", "CASCADE"),
        _fk("billing_checkout_sessions", "product_id", "products", "RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_billing_checkout_sessions"),
        sa.UniqueConstraint(
            "provider",
            "provider_session_id",
            name="uq_billing_checkout_sessions__provider_provider_session_id",
        ),
    )
    op.create_index(
        "ix_billing_checkout_sessions__user_product",
        "billing_checkout_sessions",
        ["user_id", "product_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_billing_checkout_sessions__user_product", table_name="billing_checkout_sessions"
    )
    op.drop_table("billing_checkout_sessions")
    op.drop_index("ix_billing_transactions__user_occurred", table_name="billing_transactions")
    op.drop_table("billing_transactions")
    op.drop_column("purchases", "expires_at")
    # Passes and free-form periods don't exist before this revision.
    op.execute("DELETE FROM purchases WHERE kind = 'non_renewing'")
    op.execute("ALTER TABLE purchases DROP CONSTRAINT ck_purchases__kind_enum")
    op.execute(
        "ALTER TABLE purchases ADD CONSTRAINT ck_purchases__kind_enum CHECK (kind IN "
        "('non_consumable', 'subscription_purchase', 'renewal'))"
    )
    op.drop_column("products", "sort_order")
    op.drop_column("products", "description")
    op.drop_column("products", "title")
    op.execute(
        "DELETE FROM products WHERE kind = 'non_renewing' OR "
        "(period IS NOT NULL AND period NOT IN ('P1M', 'P1Y'))"
    )
    op.execute("ALTER TABLE products DROP CONSTRAINT ck_products__period_format")
    op.execute(
        "ALTER TABLE products ADD CONSTRAINT ck_products__period_enum "
        "CHECK (period IN ('P1M', 'P1Y'))"
    )
    op.execute("ALTER TABLE products DROP CONSTRAINT ck_products__kind_enum")
    op.execute(
        "ALTER TABLE products ADD CONSTRAINT ck_products__kind_enum "
        "CHECK (kind IN ('auto_renewable', 'non_consumable'))"
    )
