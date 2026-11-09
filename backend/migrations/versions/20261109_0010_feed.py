"""Feed: ranked snapshots and negative feedback (BL-1.13).

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "feed_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("post_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("context", postgresql.JSONB(), nullable=False),
        sa.Column("weights_version", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_feed_sessions__user_id__users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_feed_sessions"),
    )
    op.create_index("ix_feed_sessions__expires_at", "feed_sessions", ["expires_at"])

    op.create_table(
        "feed_feedback",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.CheckConstraint(
            "kind IN ('hide', 'not_interested', 'see_less_author')",
            name="ck_feed_feedback__kind_enum",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_feed_feedback__user_id__users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["post_id"], ["posts.id"], name="fk_feed_feedback__post_id__posts", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "post_id", "kind", name="pk_feed_feedback"),
    )
    op.create_index(
        "ix_feed_feedback__user_created", "feed_feedback", ["user_id", sa.text("created_at DESC")]
    )


def downgrade() -> None:
    op.drop_table("feed_feedback")
    op.drop_table("feed_sessions")
