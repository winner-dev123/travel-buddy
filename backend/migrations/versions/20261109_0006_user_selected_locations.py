"""Location: user-selected destinations (browse, upcoming, saved) (BL-1.07).

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-09

Destinations a user chose, never device positions (LOC-003).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_selected_locations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("destination_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "share_for_discovery", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('browse', 'upcoming', 'saved')", name="ck_user_selected_locations__kind_enum"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_selected_locations__user_id__users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["destination_id"],
            ["destinations.id"],
            name="fk_user_selected_locations__destination_id__destinations",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_selected_locations"),
    )
    op.create_index(
        "uq_user_selected_locations__one_browse",
        "user_selected_locations",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'browse'"),
    )
    op.create_index(
        "uq_user_selected_locations__user_destination_kind",
        "user_selected_locations",
        ["user_id", "destination_id", "kind"],
        unique=True,
    )
    op.create_index(
        "ix_user_selected_locations__destination",
        "user_selected_locations",
        ["destination_id", "kind"],
    )


def downgrade() -> None:
    op.drop_table("user_selected_locations")
