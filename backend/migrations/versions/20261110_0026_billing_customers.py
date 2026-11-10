"""Stripe customers for web checkout and the Customer Portal (BL-3.14; ADR-0012).

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _check(name: str, column: str, values: Sequence[str]) -> sa.CheckConstraint:
    """``op.f``: ``name`` is final, so the naming convention does not prefix it again."""
    allowed = ", ".join(f"'{v}'" for v in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=op.f(name))


def upgrade() -> None:
    op.create_table(
        "billing_customers",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.Text(), server_default=sa.text("'stripe'"), nullable=False),
        sa.Column("provider_customer_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        _check("ck_billing_customers__provider_enum", "provider", ["stripe"]),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_billing_customers__user_id__users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("user_id", "provider", name="pk_billing_customers"),
        sa.UniqueConstraint(
            "provider",
            "provider_customer_id",
            name="uq_billing_customers__provider_provider_customer_id",
        ),
    )


def downgrade() -> None:
    op.drop_table("billing_customers")
