"""Profiles: track handle changes (PROF-003, once per 30 days).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-09

NULL means the handle is still the one generated at registration, which may be changed at once
(the first choice usually happens during onboarding).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column("handle_changed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "handle_changed_at")
