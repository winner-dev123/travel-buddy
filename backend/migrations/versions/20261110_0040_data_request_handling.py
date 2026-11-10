"""Staff handling of data subject requests: channel, handled_by, resolution (BL-6.03).

Revision ID: 0040
Revises: 0039
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHANNEL = sa.CheckConstraint(
    "channel IN ('app', 'email', 'other')", name="ck_data_subject_requests__channel_enum"
)


def upgrade() -> None:
    op.add_column(
        "data_subject_requests",
        sa.Column("channel", sa.Text(), server_default="app", nullable=False),
    )
    op.create_check_constraint(op.f(str(_CHANNEL.name)), "data_subject_requests", _CHANNEL.sqltext)
    op.add_column("data_subject_requests", sa.Column("handled_by", sa.Uuid(), nullable=True))
    op.add_column("data_subject_requests", sa.Column("resolution", sa.Text(), nullable=True))
    op.create_index(
        "ix_data_subject_requests__open",
        "data_subject_requests",
        ["requested_at"],
        postgresql_where=sa.text("status IN ('received', 'processing')"),
    )


def downgrade() -> None:
    op.drop_index("ix_data_subject_requests__open", table_name="data_subject_requests")
    op.drop_column("data_subject_requests", "resolution")
    op.drop_column("data_subject_requests", "handled_by")
    op.drop_constraint(op.f(str(_CHANNEL.name)), "data_subject_requests", type_="check")
    op.drop_column("data_subject_requests", "channel")
