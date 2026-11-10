"""Single-use realtime tickets for browsers (BL-3.15; ADR-0013).

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "realtime_tickets",
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column(
            "claims",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "issued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_realtime_tickets__user_id__users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["user_sessions.id"],
            name="fk_realtime_tickets__session_id__user_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("token_hash", name="pk_realtime_tickets"),
    )
    op.create_index("ix_realtime_tickets__expires_at", "realtime_tickets", ["expires_at"])


def downgrade() -> None:
    op.drop_table("realtime_tickets")
