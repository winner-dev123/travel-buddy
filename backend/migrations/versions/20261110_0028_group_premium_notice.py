"""Owner-lapse notice stage per group (BL-3.10; docs/07 §5).

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("travel_groups", sa.Column("premium_notice", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("travel_groups", "premium_notice")
