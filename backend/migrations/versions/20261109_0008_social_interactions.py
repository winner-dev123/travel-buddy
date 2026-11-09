"""Social: reactions, comments, bookmarks and follows (BL-1.11).

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("now()")


def _user_fk(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], ["users.id"], name=f"fk_{table}__{column}__users", ondelete="CASCADE"
    )


def _post_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["post_id"], ["posts.id"], name=f"fk_{table}__post_id__posts", ondelete="CASCADE"
    )


def upgrade() -> None:
    op.create_table(
        "reactions",
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("reaction", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.CheckConstraint(
            "reaction IN ('like', 'love', 'helpful', 'wow')", name="ck_reactions__reaction_enum"
        ),
        _post_fk("reactions"),
        _user_fk("reactions", "user_id"),
        sa.PrimaryKeyConstraint("post_id", "user_id", name="pk_reactions"),
    )
    op.create_index(
        "ix_reactions__user_created", "reactions", ["user_id", sa.text("created_at DESC")]
    )

    op.create_table(
        "comments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("parent_comment_id", sa.Uuid(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column(
            "moderation_state", sa.Text(), server_default=sa.text("'approved'"), nullable=False
        ),
        sa.Column("reply_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "moderation_state IN ('pending', 'approved', 'limited', 'removed')",
            name="ck_comments__moderation_state_enum",
        ),
        sa.CheckConstraint("char_length(body) <= 2000", name="ck_comments__body_length"),
        _post_fk("comments"),
        _user_fk("comments", "author_id"),
        sa.ForeignKeyConstraint(
            ["parent_comment_id"],
            ["comments.id"],
            name="fk_comments__parent_comment_id__comments",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_comments"),
    )
    op.create_index("ix_comments__post_created", "comments", ["post_id", "created_at"])
    op.create_index("ix_comments__parent_created", "comments", ["parent_comment_id", "created_at"])

    op.create_table(
        "bookmarks",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        _user_fk("bookmarks", "user_id"),
        _post_fk("bookmarks"),
        sa.PrimaryKeyConstraint("user_id", "post_id", name="pk_bookmarks"),
    )
    op.create_index(
        "ix_bookmarks__user_created", "bookmarks", ["user_id", sa.text("created_at DESC")]
    )

    op.create_table(
        "follows",
        sa.Column("follower_id", sa.Uuid(), nullable=False),
        sa.Column("followee_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.CheckConstraint("status IN ('active', 'pending')", name="ck_follows__status_enum"),
        sa.CheckConstraint("follower_id <> followee_id", name="ck_follows__not_self"),
        _user_fk("follows", "follower_id"),
        _user_fk("follows", "followee_id"),
        sa.PrimaryKeyConstraint("follower_id", "followee_id", name="pk_follows"),
    )
    op.create_index("ix_follows__followee_status", "follows", ["followee_id", "status"])


def downgrade() -> None:
    op.drop_table("follows")
    op.drop_table("bookmarks")
    op.drop_table("comments")
    op.drop_table("reactions")
