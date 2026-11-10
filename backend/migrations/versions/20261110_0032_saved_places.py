"""Saved places (BL-4.04; TRIP-003).

Revision ID: 0032
Revises: 0031
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_places",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("place_id", sa.Uuid(), nullable=False),
        sa.Column("collection", sa.Text(), server_default=sa.text("'default'"), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(collection) BETWEEN 1 AND 40",
            name=op.f("ck_saved_places__collection_length"),
        ),
        sa.CheckConstraint("char_length(note) <= 500", name=op.f("ck_saved_places__note_length")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_saved_places__user_id__users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["place_id"],
            ["places.id"],
            name="fk_saved_places__place_id__places",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "place_id", "collection", name="pk_saved_places"),
    )
    op.create_index(
        "ix_saved_places__user_created", "saved_places", ["user_id", sa.text("created_at DESC")]
    )


def downgrade() -> None:
    op.drop_table("saved_places")
