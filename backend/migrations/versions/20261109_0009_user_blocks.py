"""Trust and safety: user blocks (BL-1.12, SAFE-001).

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_blocks",
        sa.Column("blocker_id", sa.Uuid(), nullable=False),
        sa.Column("blocked_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("blocker_id <> blocked_id", name="ck_user_blocks__not_self"),
        sa.ForeignKeyConstraint(
            ["blocker_id"],
            ["users.id"],
            name="fk_user_blocks__blocker_id__users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["blocked_id"],
            ["users.id"],
            name="fk_user_blocks__blocked_id__users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("blocker_id", "blocked_id", name="pk_user_blocks"),
    )
    op.create_index("ix_user_blocks__blocked", "user_blocks", ["blocked_id"])


def downgrade() -> None:
    op.drop_table("user_blocks")
