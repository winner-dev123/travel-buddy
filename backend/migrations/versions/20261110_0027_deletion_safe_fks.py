"""Account deletion works for group owners and purchasers (AUTH-010, GRP-011, docs/04 §14).

Billing records outlive the account pseudonymized (``user_id`` SET NULL); the Stripe customer
mapping goes with it. Groups are handed over before the owner's row is deleted, so
``travel_groups.owner_id`` only becomes NULL for an archived group nobody was left in.

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NULLABLE = (
    ("subscriptions", "user_id"),
    ("purchases", "user_id"),
    ("subscription_entitlements", "user_id"),
    ("travel_groups", "owner_id"),
)


def _swap(table: str, column: str, ondelete: str) -> None:
    name = f"fk_{table}__{column}__users"
    op.drop_constraint(name, table, type_="foreignkey")
    op.create_foreign_key(name, table, "users", [column], ["id"], ondelete=ondelete)


def upgrade() -> None:
    for table, column in NULLABLE:
        op.alter_column(table, column, existing_type=sa.Uuid(), nullable=True)
        _swap(table, column, "SET NULL")
    _swap("billing_customers", "user_id", "CASCADE")


def downgrade() -> None:
    _swap("billing_customers", "user_id", "RESTRICT")
    for table, column in NULLABLE:
        _swap(table, column, "RESTRICT")
        op.alter_column(table, column, existing_type=sa.Uuid(), nullable=False)
