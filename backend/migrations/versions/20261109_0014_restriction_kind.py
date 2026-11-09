"""Moderation restrictions: ``moderation_actions.restriction_kind`` (BL-1.28, SAFE-013).

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _check(name: str, column: str, values: Sequence[str]) -> sa.CheckConstraint:
    allowed = ", ".join(f"'{v}'" for v in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=name)


def upgrade() -> None:
    op.add_column("moderation_actions", sa.Column("restriction_kind", sa.Text(), nullable=True))
    # No 'restrict' rows exist anywhere yet (staff routes need a role nobody holds outside tests),
    # so the pairing check is added strictly; it fails loudly rather than guessing a kind.
    # Short names: the metadata naming convention adds the "ck_<table>__" prefix.
    op.create_check_constraint(
        "restriction_kind_enum",
        "moderation_actions",
        _check(
            "ck_moderation_actions__restriction_kind_enum",
            "restriction_kind",
            [
                "posting_limited",
                "commenting_limited",
                "messaging_limited",
                "connection_requests_limited",
                "discovery_disabled",
                "media_upload_limited",
            ],
        ).sqltext,
    )
    op.create_check_constraint(
        "restriction_kind_required",
        "moderation_actions",
        "(action = 'restrict') = (restriction_kind IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("restriction_kind_required", "moderation_actions", type_="check")
    op.drop_constraint("restriction_kind_enum", "moderation_actions", type_="check")
    op.drop_column("moderation_actions", "restriction_kind")
