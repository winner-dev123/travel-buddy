"""Rate-limit counters for deployments without Redis (BL-1.15).

UNLOGGED: disposable counters, no WAL. Rows expire two windows after they start.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rate_limit_counters",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("window_start", sa.BigInteger(), nullable=False),
        sa.Column("hits", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", "window_start", name="pk_rate_limit_counters"),
        prefixes=["UNLOGGED"],
    )
    op.create_index("ix_rate_limit_counters__expires_at", "rate_limit_counters", ["expires_at"])


def downgrade() -> None:
    op.drop_table("rate_limit_counters")
