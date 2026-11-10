"""Offline packages and their device licenses (BL-4.08; OFF-001, OFF-004, OFF-005).

Revision ID: 0035
Revises: 0034
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _check(name: str, column: str, values: Sequence[str]) -> sa.CheckConstraint:
    """``op.f``: ``name`` is final, so the naming convention does not prefix it again."""
    allowed = ", ".join(f"'{v}'" for v in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=op.f(name))


def _ts(name: str, *, nullable: bool = True, now: bool = False) -> sa.Column[sa.DateTime]:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()") if now else None,
        nullable=nullable,
    )


def upgrade() -> None:
    op.create_table(
        "offline_packages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("destination_id", sa.Uuid(), nullable=False),
        sa.Column("locale", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("files", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("total_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("tier", sa.Text(), server_default=sa.text("'free'"), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("min_app_version", sa.Text(), server_default=sa.text("'1.0.0'"), nullable=False),
        sa.Column("content_license", sa.Text(), nullable=False),
        _ts("license_expires_at"),
        sa.Column("status", sa.Text(), server_default=sa.text("'building'"), nullable=False),
        _ts("published_at"),
        _ts("created_at", nullable=False, now=True),
        _check(
            "ck_offline_packages__kind_enum",
            "kind",
            ["guide", "audio_tour", "map_region", "bundle"],
        ),
        _check("ck_offline_packages__status_enum", "status", ["building", "published", "retired"]),
        _check("ck_offline_packages__tier_enum", "tier", ["free", "premium", "purchasable"]),
        sa.ForeignKeyConstraint(
            ["destination_id"],
            ["destinations.id"],
            name="fk_offline_packages__destination_id__destinations",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="fk_offline_packages__product_id__products",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_offline_packages"),
        sa.UniqueConstraint(
            "destination_id",
            "locale",
            "kind",
            "version",
            name="uq_offline_packages__destination_id_locale_kind_version",
        ),
    )
    op.create_index(
        "ix_offline_packages__destination_status",
        "offline_packages",
        ["destination_id", "status"],
    )

    op.create_table(
        "offline_package_licenses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("package_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Text(), nullable=False),
        _ts("granted_at", nullable=False, now=True),
        _ts("expires_at"),
        _ts("revoked_at"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_offline_package_licenses__user_id__users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["package_id"],
            ["offline_packages.id"],
            name="fk_offline_package_licenses__package_id__offline_packages",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_offline_package_licenses"),
        sa.UniqueConstraint(
            "user_id",
            "package_id",
            "device_id",
            name="uq_offline_package_licenses__user_id_package_id_device_id",
        ),
    )
    op.create_index(
        "ix_offline_package_licenses__user_active",
        "offline_package_licenses",
        ["user_id", "revoked_at"],
    )


def downgrade() -> None:
    op.drop_table("offline_package_licenses")
    op.drop_table("offline_packages")
