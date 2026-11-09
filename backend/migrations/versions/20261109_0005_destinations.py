"""Destinations: hierarchy, localizations, boundaries (BL-1.05).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-09

Centroids are plain lat/lng columns; only ``destination_boundaries`` needs PostGIS (it is skipped,
with a notice, on databases without it). Search uses a trigram index on f_unaccent(lower(name)).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geography
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("now()")


def _check(name: str, column: str, values: Sequence[str]) -> sa.CheckConstraint:
    allowed = ", ".join(f"'{v}'" for v in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=name)


def _postgis_installed() -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(sa.text("SELECT 1 FROM pg_extension WHERE extname = 'postgis'")).scalar()
    )


def upgrade() -> None:
    op.create_table(
        "destinations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("country_code", sa.Text(), nullable=False),
        sa.Column("continent", sa.Text(), nullable=False),
        sa.Column("cover_media_id", sa.Uuid(), nullable=True),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("path_segment", sa.Text(), nullable=False),
        sa.Column("default_name", sa.Text(), nullable=False),
        sa.Column("centroid_lat", sa.Double(), nullable=False),
        sa.Column("centroid_lng", sa.Double(), nullable=False),
        sa.Column("time_zone", sa.Text(), nullable=False),
        sa.Column("path", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("depth", sa.SmallInteger(), nullable=False),
        sa.Column("geonames_id", sa.BigInteger(), nullable=True),
        sa.Column("osm_relation_id", sa.BigInteger(), nullable=True),
        sa.Column("wikidata_id", sa.Text(), nullable=True),
        sa.Column("popularity_score", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("is_featured", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("has_guides", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        _check(
            "ck_destinations__kind_enum",
            "kind",
            ["country", "admin_region", "city", "district", "neighborhood", "area"],
        ),
        _check(
            "ck_destinations__continent_enum",
            "continent",
            [
                "africa",
                "asia",
                "europe",
                "middle_east",
                "north_america",
                "central_america_caribbean",
                "south_america",
                "oceania",
            ],
        ),
        _check("ck_destinations__status_enum", "status", ["active", "hidden"]),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["destinations.id"],
            name="fk_destinations__parent_id__destinations",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_destinations"),
    )
    op.create_index("uq_destinations__slug", "destinations", ["slug"], unique=True)
    op.create_index(
        "uq_destinations__sibling_segment",
        "destinations",
        [
            sa.text("COALESCE(parent_id, '00000000-0000-0000-0000-000000000000'::uuid)"),
            "path_segment",
        ],
        unique=True,
    )
    op.create_index("ix_destinations__parent", "destinations", ["parent_id"])
    op.create_index("ix_destinations__path", "destinations", ["path"], postgresql_using="gin")
    op.create_index(
        "ix_destinations__directory",
        "destinations",
        ["continent", sa.text("popularity_score DESC")],
        postgresql_where=sa.text("status = 'active'"),
    )
    for column in ("geonames_id", "osm_relation_id", "wikidata_id"):
        op.create_index(
            f"uq_destinations__{column}",
            "destinations",
            [column],
            unique=True,
            postgresql_where=sa.text(f"{column} IS NOT NULL"),
        )

    op.create_table(
        "destination_localizations",
        sa.Column("destination_id", sa.Uuid(), nullable=False),
        sa.Column("locale", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "alt_names", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("tagline", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "char_length(tagline) <= 140", name="ck_destination_localizations__tagline_length"
        ),
        sa.ForeignKeyConstraint(
            ["destination_id"],
            ["destinations.id"],
            name="fk_destination_localizations__destination_id__destinations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("destination_id", "locale", name="pk_destination_localizations"),
    )
    op.execute(
        "CREATE INDEX ix_destination_localizations__name_trgm ON destination_localizations "
        "USING gin (f_unaccent(lower(name)) gin_trgm_ops)"
    )

    if _postgis_installed():
        op.create_table(
            "destination_boundaries",
            sa.Column("destination_id", sa.Uuid(), nullable=False),
            sa.Column(
                "boundary",
                Geography(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False),
                nullable=False,
            ),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
            sa.ForeignKeyConstraint(
                ["destination_id"],
                ["destinations.id"],
                name="fk_destination_boundaries__destination_id__destinations",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("destination_id", name="pk_destination_boundaries"),
        )
        op.create_index(
            "ix_destination_boundaries__boundary",
            "destination_boundaries",
            ["boundary"],
            postgresql_using="gist",
        )
    else:
        op.execute(
            "DO $$ BEGIN RAISE NOTICE "
            "'PostGIS not installed: destination_boundaries skipped (point resolution off)'; END $$"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS destination_boundaries")
    op.drop_table("destination_localizations")
    op.drop_table("destinations")
