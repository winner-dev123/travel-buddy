"""Runtime overrides of quota limits and the group admin grace period (BL-6.02).

Revision ID: 0041
Revises: 0040
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0041"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "entitlement_policy_overrides",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column(
            "quotas",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("group_admin_grace_days", sa.Integer(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.CheckConstraint("id = 1", name=op.f("ck_entitlement_policy_overrides__singleton")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entitlement_policy_overrides")),
    )


def downgrade() -> None:
    op.drop_table("entitlement_policy_overrides")
