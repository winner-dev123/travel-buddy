"""Destination guides and audio tours (BL-4.07; GUIDE-004, GUIDE-005, GUIDE-006).

Revision ID: 0034
Revises: 0033
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0034"
down_revision: str | None = "0033"
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


def _fk(table: str, column: str, referred: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], [f"{referred}.id"], name=f"fk_{table}__{column}__{referred}", ondelete=ondelete
    )


def upgrade() -> None:
    op.create_table(
        "destination_guides",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("destination_id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("locale", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tier", sa.Text(), server_default=sa.text("'free'"), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("content_license", sa.Text(), nullable=False),
        sa.Column("attribution", sa.Text(), nullable=True),
        _ts("rights_expire_at"),
        _ts("published_at"),
        _ts("updated_at", nullable=False, now=True),
        _check("ck_destination_guides__tier_enum", "tier", ["free", "premium", "purchasable"]),
        _check("ck_destination_guides__status_enum", "status", ["draft", "published", "retired"]),
        _fk("destination_guides", "destination_id", "destinations", "RESTRICT"),
        _fk("destination_guides", "product_id", "products", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_destination_guides"),
        sa.UniqueConstraint(
            "destination_id",
            "locale",
            "slug",
            "version",
            name="uq_destination_guides__destination_id_locale_slug_version",
        ),
    )
    op.create_index(
        "ix_destination_guides__destination_status",
        "destination_guides",
        ["destination_id", "status"],
    )

    op.create_table(
        "audio_tours",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("destination_id", sa.Uuid(), nullable=False),
        sa.Column("guide_id", sa.Uuid(), nullable=True),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("locale", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("tier", sa.Text(), server_default=sa.text("'free'"), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("content_license", sa.Text(), nullable=False),
        _ts("rights_expire_at"),
        _ts("published_at"),
        _ts("updated_at", nullable=False, now=True),
        _check("ck_audio_tours__tier_enum", "tier", ["free", "premium", "purchasable"]),
        _check("ck_audio_tours__status_enum", "status", ["draft", "published", "retired"]),
        _fk("audio_tours", "destination_id", "destinations", "RESTRICT"),
        _fk("audio_tours", "guide_id", "destination_guides", "SET NULL"),
        _fk("audio_tours", "product_id", "products", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_audio_tours"),
        sa.UniqueConstraint(
            "destination_id",
            "locale",
            "slug",
            "version",
            name="uq_audio_tours__destination_id_locale_slug_version",
        ),
    )
    op.create_index(
        "ix_audio_tours__destination_status", "audio_tours", ["destination_id", "status"]
    )

    op.create_table(
        "audio_tour_stops",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tour_id", sa.Uuid(), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False),
        sa.Column("place_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("audio_media_id", sa.Uuid(), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column(
            "trigger_radius_m", sa.SmallInteger(), server_default=sa.text("50"), nullable=False
        ),
        sa.Column("duration_s", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "trigger_radius_m BETWEEN 10 AND 1000",
            name=op.f("ck_audio_tour_stops__trigger_radius_range"),
        ),
        sa.CheckConstraint("duration_s >= 0", name=op.f("ck_audio_tour_stops__duration_positive")),
        _fk("audio_tour_stops", "tour_id", "audio_tours", "CASCADE"),
        _fk("audio_tour_stops", "place_id", "places", "RESTRICT"),
        _fk("audio_tour_stops", "audio_media_id", "media_assets", "RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_audio_tour_stops"),
        sa.UniqueConstraint(
            "tour_id", "sort_order", name="uq_audio_tour_stops__tour_id_sort_order"
        ),
    )


def downgrade() -> None:
    for table in ("audio_tour_stops", "audio_tours", "destination_guides"):
        op.drop_table(table)
