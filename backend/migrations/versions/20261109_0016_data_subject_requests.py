"""Data subject requests (account deletion now, export later) (BL-1.17).

``user_id`` has no foreign key: the record of a completed deletion outlives the account.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _check(name: str, column: str, values: Sequence[str]) -> sa.CheckConstraint:
    """``op.f``: ``name`` is final, so the naming convention does not prefix it again."""
    allowed = ", ".join(f"'{v}'" for v in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=op.f(name))


def upgrade() -> None:
    op.create_table(
        "data_subject_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        _check(
            "ck_data_subject_requests__kind_enum",
            "kind",
            ["export", "deletion", "rectification"],
        ),
        _check(
            "ck_data_subject_requests__status_enum",
            "status",
            ["received", "processing", "completed", "rejected", "cancelled"],
        ),
        sa.PrimaryKeyConstraint("id", name="pk_data_subject_requests"),
    )
    op.create_index(
        "ix_data_subject_requests__user_id",
        "data_subject_requests",
        ["user_id", sa.text("requested_at DESC")],
    )


def downgrade() -> None:
    op.drop_table("data_subject_requests")
