"""World gazetteer (ADR-0035): towns of 5,000+ people and well-known tourist places.

* ``destinations.population`` and ``region_name`` show where a town is ("Campinas, São Paulo") and
  let a device point resolve to the town it is in when no polygon covers it (LOC-005).
* ``destinations.in_directory``: gazetteer towns are searchable, resolvable and postable but stay
  out of the directory, children lists and sitemap until an editor lists them.
* Indexes: nearest town by centroid, and trigram indexes on default and alternative names so
  search stays index-backed with ~65,000 destinations. ``f_search_names`` is the IMMUTABLE text
  form of an alternative-name array that the index needs.

The data itself is loaded by ``python -m app.modules.destinations.world_catalog load``.

Revision ID: 0049
Revises: 0048
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEARCH_NAMES_FUNCTION = """
CREATE OR REPLACE FUNCTION public.f_search_names(text[]) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
AS $$ SELECT public.f_unaccent(lower(array_to_string($1, ' | '))) $$
"""


def upgrade() -> None:
    op.add_column("destinations", sa.Column("population", sa.BigInteger(), nullable=True))
    op.add_column("destinations", sa.Column("region_name", sa.Text(), nullable=True))
    op.add_column(
        "destinations",
        sa.Column("in_directory", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.create_index(
        "ix_destinations__town_centroid",
        "destinations",
        ["centroid_lat", "centroid_lng"],
        postgresql_where=sa.text("kind = 'city' AND status = 'active'"),
    )
    op.execute(SEARCH_NAMES_FUNCTION)
    op.execute(
        "CREATE INDEX ix_destinations__default_name_trgm ON destinations "
        "USING gin (f_unaccent(lower(default_name)) gin_trgm_ops)"
    )
    op.execute(
        "CREATE INDEX ix_destination_localizations__alt_names_trgm ON destination_localizations "
        "USING gin (f_search_names(alt_names) gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_destination_localizations__alt_names_trgm")
    op.execute("DROP INDEX IF EXISTS ix_destinations__default_name_trgm")
    op.execute("DROP FUNCTION IF EXISTS public.f_search_names(text[])")
    op.drop_index("ix_destinations__town_centroid", table_name="destinations")
    op.drop_column("destinations", "in_directory")
    op.drop_column("destinations", "region_name")
    op.drop_column("destinations", "population")
