"""Media attached to posts (BL-1.08 / BL-1.10).

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "post_media",
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("media_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["post_id"], ["posts.id"], name="fk_post_media__post_id__posts", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["media_id"],
            ["media_assets.id"],
            name="fk_post_media__media_id__media_assets",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("post_id", "media_id", name="pk_post_media"),
        sa.UniqueConstraint("post_id", "position", name=op.f("uq_post_media__post_id_position")),
    )
    op.create_index("ix_post_media__media_id", "post_media", ["media_id"])


def downgrade() -> None:
    op.drop_table("post_media")
