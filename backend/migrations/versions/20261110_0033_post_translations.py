"""Cached machine translations of posts (BL-4.10; POST-010, I18N-006).

Revision ID: 0033
Revises: 0032
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "post_translations",
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("target_language", sa.Text(), nullable=False),
        sa.Column("source_language", sa.Text(), nullable=False),
        sa.Column("body_hash", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["posts.id"],
            name="fk_post_translations__post_id__posts",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("post_id", "target_language", name="pk_post_translations"),
    )


def downgrade() -> None:
    op.drop_table("post_translations")
