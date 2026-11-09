"""Traveler discovery sessions (BL-2.02). Deliberately no coordinate columns (ADR-0005).

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _check(name: str, column: str, values: Sequence[str]) -> sa.CheckConstraint:
    """``op.f``: ``name`` is final, so the naming convention does not prefix it again."""
    allowed = ", ".join(f"'{v}'" for v in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=op.f(name))


def upgrade() -> None:
    op.create_table(
        "traveler_discovery_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("destination_id", sa.Uuid(), nullable=False),
        sa.Column("area_destination_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("visibility", sa.Text(), server_default=sa.text("'visible'"), nullable=False),
        sa.Column("travel_start_date", sa.Date(), nullable=True),
        sa.Column("travel_end_date", sa.Date(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        _check("ck_traveler_discovery_sessions__source_enum", "source", ["gps_resolved", "manual"]),
        _check(
            "ck_traveler_discovery_sessions__visibility_enum",
            "visibility",
            ["visible", "invisible"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_traveler_discovery_sessions__user_id__users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["destination_id"],
            ["destinations.id"],
            name="fk_traveler_discovery_sessions__destination_id__destinations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["area_destination_id"],
            ["destinations.id"],
            name="fk_traveler_discovery_sessions__area_destination_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_traveler_discovery_sessions"),
    )
    op.create_index(
        "uq_traveler_discovery_sessions__open_per_user",
        "traveler_discovery_sessions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )
    op.create_index(
        "ix_traveler_discovery_sessions__visible",
        "traveler_discovery_sessions",
        ["destination_id", "expires_at"],
        postgresql_where=sa.text("ended_at IS NULL AND visibility = 'visible'"),
    )
    op.create_index(
        "ix_traveler_discovery_sessions__user_started",
        "traveler_discovery_sessions",
        ["user_id", sa.text("started_at DESC")],
    )


def downgrade() -> None:
    op.drop_table("traveler_discovery_sessions")
