"""Media assets (BL-1.08).

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _check(name: str, column: str, values: Sequence[str]) -> sa.CheckConstraint:
    """``op.f``: ``name`` is final, so the naming convention does not prefix it again."""
    allowed = ", ".join(f"'{v}'" for v in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=op.f(name))


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending_upload'"), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("alt_text", sa.Text(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("quarantine_key", sa.Text(), nullable=False),
        sa.Column(
            "variants", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        _check(
            "ck_media_assets__purpose_enum",
            "purpose",
            ["post", "avatar", "message", "group_cover", "challenge"],
        ),
        _check(
            "ck_media_assets__status_enum",
            "status",
            ["pending_upload", "scanning", "ready", "rejected", "deleted"],
        ),
        _check(
            "ck_media_assets__rejection_reason_enum",
            "rejection_reason",
            [
                "malware",
                "policy_violation",
                "type_mismatch",
                "hash_mismatch",
                "too_large",
                "processing_failed",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_media_assets__owner_id__users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_media_assets"),
    )
    op.create_index(
        "ix_media_assets__owner_created", "media_assets", ["owner_id", sa.text("created_at DESC")]
    )
    op.create_index("ix_media_assets__status_created", "media_assets", ["status", "created_at"])


def downgrade() -> None:
    op.drop_table("media_assets")
