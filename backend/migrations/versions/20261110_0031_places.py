"""Places catalog from licensed sources (BL-4.01; DEST-003, LOC-009).

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _check(name: str, column: str, values: Sequence[str]) -> sa.CheckConstraint:
    """``op.f``: ``name`` is final, so the naming convention does not prefix it again."""
    allowed = ", ".join(f"'{v}'" for v in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=op.f(name))


def upgrade() -> None:
    op.create_table(
        "places",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("destination_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("default_name", sa.Text(), nullable=False),
        sa.Column("lat", sa.Double(), nullable=False),
        sa.Column("lng", sa.Double(), nullable=False),
        sa.Column("address", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_place_id", sa.Text(), nullable=False),
        sa.Column("license", sa.Text(), nullable=False),
        sa.Column("attribution_text", sa.Text(), nullable=False),
        sa.Column("attribution_url", sa.Text(), nullable=True),
        sa.Column("data_freshness_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "attributes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("popularity_score", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        _check(
            "ck_places__category_enum",
            "category",
            [
                "attraction",
                "restaurant",
                "cafe",
                "bar",
                "museum",
                "beach",
                "trail",
                "viewpoint",
                "park",
                "market",
                "lodging",
                "transit_hub",
                "other",
            ],
        ),
        _check("ck_places__status_enum", "status", ["active", "closed_permanently", "hidden"]),
        sa.CheckConstraint(
            "lat BETWEEN -90 AND 90 AND lng BETWEEN -180 AND 180",
            name=op.f("ck_places__coordinates"),
        ),
        sa.ForeignKeyConstraint(
            ["destination_id"],
            ["destinations.id"],
            name="fk_places__destination_id__destinations",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_places"),
        sa.UniqueConstraint(
            "provider", "provider_place_id", name="uq_places__provider_provider_place_id"
        ),
    )
    op.create_index("ix_places__destination_category", "places", ["destination_id", "category"])
    op.create_index("ix_places__lat_lng", "places", ["lat", "lng"])
    op.execute(
        "CREATE INDEX ix_places__name_trgm ON places "
        "USING gin (f_unaccent(lower(default_name)) gin_trgm_ops)"
    )

    op.create_table(
        "place_localizations",
        sa.Column("place_id", sa.Uuid(), nullable=False),
        sa.Column("locale", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["place_id"],
            ["places.id"],
            name="fk_place_localizations__place_id__places",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("place_id", "locale", name="pk_place_localizations"),
    )
    op.execute(
        "CREATE INDEX ix_place_localizations__name_trgm ON place_localizations "
        "USING gin (f_unaccent(lower(name)) gin_trgm_ops)"
    )

    # Itinerary items may now reference catalog places (BL-4.04 left the FK for this module).
    op.create_foreign_key(
        "fk_itinerary_items__place_id__places",
        "itinerary_items",
        "places",
        ["place_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_itinerary_items__place_id__places", "itinerary_items", type_="foreignkey"
    )
    op.drop_table("place_localizations")
    op.drop_table("places")
