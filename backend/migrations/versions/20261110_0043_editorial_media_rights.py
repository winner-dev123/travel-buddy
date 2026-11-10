"""Editorial media: attribution, verified rights and platform ownership (DEST-007).

Destination covers (``destinations.cover_media_id``) stay without a foreign key: media rows hang
off users, and the catalog must not be reachable from the user graph (``TRUNCATE users CASCADE``
in tests, account erasure). Covers are checked when set and again on every read.

Revision ID: 0043
Revises: 0042
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0043"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Literal SQL so the static schema test can compare it with ``MediaPurpose``.
_PURPOSES = sa.CheckConstraint(
    "purpose IN ('post', 'avatar', 'message', 'group_cover', 'challenge', 'editorial')",
    name="ck_media_assets__purpose_enum",
)
_OLD_PURPOSES = "purpose IN ('post', 'avatar', 'message', 'group_cover', 'challenge')"


def upgrade() -> None:
    op.add_column("media_assets", sa.Column("attribution_text", sa.Text(), nullable=True))
    op.add_column("media_assets", sa.Column("attribution_license", sa.Text(), nullable=True))
    op.add_column("media_assets", sa.Column("attribution_url", sa.Text(), nullable=True))
    op.add_column(
        "media_assets",
        sa.Column("rights_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("media_assets", sa.Column("rights_verified_by", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_media_assets__rights_verified_by__users"),
        "media_assets",
        "users",
        ["rights_verified_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint(op.f("ck_media_assets__purpose_enum"), "media_assets", type_="check")
    op.create_check_constraint(
        op.f("ck_media_assets__purpose_enum"), "media_assets", _PURPOSES.sqltext
    )
    # Verified editorial media belongs to the platform: it outlives the uploader's account.
    op.alter_column("media_assets", "owner_id", existing_type=sa.Uuid(), nullable=True)
    op.create_check_constraint(
        op.f("ck_media_assets__owner_required"),
        "media_assets",
        "owner_id IS NOT NULL OR purpose = 'editorial'",
    )
    op.create_check_constraint(
        op.f("ck_media_assets__editorial_attribution"),
        "media_assets",
        "purpose <> 'editorial' OR (attribution_text IS NOT NULL "
        "AND attribution_license IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_media_assets__rights_editorial_only"),
        "media_assets",
        "rights_verified_at IS NULL OR purpose = 'editorial'",
    )


def downgrade() -> None:
    op.execute("DELETE FROM media_assets WHERE purpose = 'editorial'")
    op.drop_constraint(
        op.f("ck_media_assets__rights_editorial_only"), "media_assets", type_="check"
    )
    op.drop_constraint(
        op.f("ck_media_assets__editorial_attribution"), "media_assets", type_="check"
    )
    op.drop_constraint(op.f("ck_media_assets__owner_required"), "media_assets", type_="check")
    op.alter_column("media_assets", "owner_id", existing_type=sa.Uuid(), nullable=False)
    op.execute("UPDATE destinations SET cover_media_id = NULL WHERE cover_media_id IS NOT NULL")
    op.drop_constraint(op.f("ck_media_assets__purpose_enum"), "media_assets", type_="check")
    op.create_check_constraint(op.f("ck_media_assets__purpose_enum"), "media_assets", _OLD_PURPOSES)
    op.drop_constraint(
        op.f("fk_media_assets__rights_verified_by__users"), "media_assets", type_="foreignkey"
    )
    op.drop_column("media_assets", "rights_verified_by")
    op.drop_column("media_assets", "rights_verified_at")
    op.drop_column("media_assets", "attribution_url")
    op.drop_column("media_assets", "attribution_license")
    op.drop_column("media_assets", "attribution_text")
