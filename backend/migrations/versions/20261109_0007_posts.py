"""Social: posts, destination fan-out and tags (BL-1.10).

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("now()")


def _check(name: str, column: str, values: Sequence[str]) -> sa.CheckConstraint:
    allowed = ", ".join(f"'{v}'" for v in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=name)


def upgrade() -> None:
    op.create_table(
        "posts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("visibility", sa.Text(), nullable=False),
        sa.Column("place_id", sa.Uuid(), nullable=True),
        sa.Column("location_precision", sa.Text(), nullable=False),
        sa.Column("primary_destination_id", sa.Uuid(), nullable=True),
        sa.Column("travel_date", sa.Date(), nullable=True),
        sa.Column("rating", sa.SmallInteger(), nullable=True),
        sa.Column("trip_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'published'"), nullable=False),
        sa.Column(
            "moderation_state", sa.Text(), server_default=sa.text("'approved'"), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reaction_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("comment_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("bookmark_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("share_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        _check(
            "ck_posts__kind_enum",
            "kind",
            [
                "text",
                "photo",
                "video",
                "story",
                "attraction_recommendation",
                "restaurant_recommendation",
                "review",
                "tip",
                "itinerary_summary",
                "experience",
            ],
        ),
        _check(
            "ck_posts__visibility_enum",
            "visibility",
            ["public", "followers", "connections", "private"],
        ),
        _check(
            "ck_posts__location_precision_enum",
            "location_precision",
            ["none", "destination", "place"],
        ),
        _check("ck_posts__status_enum", "status", ["draft", "published", "deleted"]),
        _check(
            "ck_posts__moderation_state_enum",
            "moderation_state",
            ["pending", "approved", "limited", "removed"],
        ),
        sa.CheckConstraint(
            "rating IS NULL OR (kind = 'review' AND rating BETWEEN 1 AND 5)",
            name="ck_posts__rating_only_reviews",
        ),
        sa.CheckConstraint(
            "(location_precision = 'none') = (primary_destination_id IS NULL)",
            name="ck_posts__destination_required_unless_none",
        ),
        sa.CheckConstraint("char_length(body) <= 5000", name="ck_posts__body_length"),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], name="fk_posts__author_id__users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["primary_destination_id"],
            ["destinations.id"],
            name="fk_posts__primary_destination_id__destinations",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_posts"),
    )
    op.create_index(
        "ix_posts__author_published",
        "posts",
        ["author_id", sa.text("published_at DESC")],
        postgresql_where=sa.text("status = 'published'"),
    )
    op.create_index(
        "ix_posts__public_published",
        "posts",
        [sa.text("published_at DESC")],
        postgresql_where=sa.text(
            "status = 'published' AND visibility = 'public' "
            "AND moderation_state IN ('approved', 'pending')"
        ),
    )

    op.create_table(
        "post_destinations",
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("destination_id", sa.Uuid(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("depth_from_primary", sa.SmallInteger(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("visibility_public", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["post_id"],
            ["posts.id"],
            name="fk_post_destinations__post_id__posts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["destination_id"],
            ["destinations.id"],
            name="fk_post_destinations__destination_id__destinations",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("post_id", "destination_id", name="pk_post_destinations"),
    )
    op.create_index(
        "ix_post_destinations__feed",
        "post_destinations",
        ["destination_id", sa.text("published_at DESC")],
        postgresql_where=sa.text("visibility_public"),
    )

    op.create_table(
        "post_tags",
        sa.Column("post_id", sa.Uuid(), nullable=False),
        sa.Column("tag", postgresql.CITEXT(), nullable=False),
        sa.ForeignKeyConstraint(
            ["post_id"], ["posts.id"], name="fk_post_tags__post_id__posts", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("post_id", "tag", name="pk_post_tags"),
    )
    op.create_index("ix_post_tags__tag", "post_tags", ["tag"])


def downgrade() -> None:
    op.drop_table("post_tags")
    op.drop_table("post_destinations")
    op.drop_table("posts")
