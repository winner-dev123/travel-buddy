"""Staff-managed keyword filter for direct messages from new connections (SAFE-006).

Revision ID: 0044
Revises: 0043
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "message_filter_policies",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column(
            "terms",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("new_connection_days", sa.Integer(), server_default=sa.text("7"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("id = 1", name=op.f("ck_message_filter_policies__singleton")),
        sa.CheckConstraint(
            "new_connection_days BETWEEN 0 AND 90",
            name=op.f("ck_message_filter_policies__days_range"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_message_filter_policies")),
    )


def downgrade() -> None:
    op.drop_table("message_filter_policies")
