"""Data exports: archive key, link expiry, one active export per user (BL-6.03; AUTH-011).

Revision ID: 0039
Revises: 0038
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0039"
down_revision: str | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("data_subject_requests", sa.Column("artifact_key", sa.Text(), nullable=True))
    op.add_column(
        "data_subject_requests",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_data_subject_requests__active_export",
        "data_subject_requests",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'export' AND status IN ('received', 'processing')"),
    )


def downgrade() -> None:
    op.drop_index("uq_data_subject_requests__active_export", table_name="data_subject_requests")
    op.drop_column("data_subject_requests", "expires_at")
    op.drop_column("data_subject_requests", "artifact_key")
