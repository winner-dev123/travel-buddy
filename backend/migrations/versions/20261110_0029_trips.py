"""Trips, destinations, collaborators, itinerary days and items (BL-4.04; TRIP-001..005).

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _check(name: str, column: str, values: Sequence[str]) -> sa.CheckConstraint:
    """``op.f``: ``name`` is final, so the naming convention does not prefix it again."""
    allowed = ", ".join(f"'{v}'" for v in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=op.f(name))


def _ck(name: str, condition: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(condition, name=op.f(name))


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
        "trips",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("visibility", sa.Text(), server_default=sa.text("'private'"), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.Column("origin", sa.Text(), server_default=sa.text("'manual'"), nullable=False),
        sa.Column("ai_generation_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'planning'"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        _ts("created_at", nullable=False, now=True),
        _ts("updated_at", nullable=False, now=True),
        _ts("deleted_at"),
        _check(
            "ck_trips__visibility_enum", "visibility", ["private", "connections", "group", "public"]
        ),
        _check("ck_trips__origin_enum", "origin", ["manual", "ai_generated", "ai_assisted"]),
        _check("ck_trips__status_enum", "status", ["planning", "active", "completed", "archived"]),
        _ck("ck_trips__dates_order", "start_date <= end_date"),
        _ck("ck_trips__title_length", "char_length(title) BETWEEN 1 AND 100"),
        _fk("trips", "owner_id", "users", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_trips"),
    )
    op.create_index("ix_trips__owner", "trips", ["owner_id", sa.text("updated_at DESC")])

    op.create_table(
        "trip_destinations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trip_id", sa.Uuid(), nullable=False),
        sa.Column("destination_id", sa.Uuid(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("sort_order", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        _fk("trip_destinations", "trip_id", "trips", "CASCADE"),
        _fk("trip_destinations", "destination_id", "destinations", "RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_trip_destinations"),
        sa.UniqueConstraint(
            "trip_id", "destination_id", name="uq_trip_destinations__trip_id_destination_id"
        ),
    )
    op.create_index("ix_trip_destinations__destination_id", "trip_destinations", ["destination_id"])

    op.create_table(
        "trip_collaborators",
        sa.Column("trip_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), server_default=sa.text("'viewer'"), nullable=False),
        sa.Column("added_by", sa.Uuid(), nullable=True),
        _ts("added_at", nullable=False, now=True),
        _check("ck_trip_collaborators__role_enum", "role", ["editor", "viewer"]),
        _fk("trip_collaborators", "trip_id", "trips", "CASCADE"),
        _fk("trip_collaborators", "user_id", "users", "CASCADE"),
        _fk("trip_collaborators", "added_by", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("trip_id", "user_id", name="pk_trip_collaborators"),
    )
    op.create_index("ix_trip_collaborators__user_id", "trip_collaborators", ["user_id"])

    op.create_table(
        "itinerary_days",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trip_id", sa.Uuid(), nullable=False),
        sa.Column("day_index", sa.SmallInteger(), nullable=False),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("destination_id", sa.Uuid(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        _ts("updated_at", nullable=False, now=True),
        _fk("itinerary_days", "trip_id", "trips", "CASCADE"),
        _fk("itinerary_days", "destination_id", "destinations", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_itinerary_days"),
        sa.UniqueConstraint("trip_id", "day_index", name="uq_itinerary_days__trip_id_day_index"),
    )

    op.create_table(
        "itinerary_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("day_id", sa.Uuid(), nullable=False),
        sa.Column("sort_order", sa.Numeric(30, 15), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("place_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("origin", sa.Text(), server_default=sa.text("'user'"), nullable=False),
        sa.Column("ai_confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("unverified", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "source_attribution",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        _ts("data_freshness_at"),
        _ts("client_updated_at"),
        _ts("created_at", nullable=False, now=True),
        _ts("updated_at", nullable=False, now=True),
        _ts("deleted_at"),
        _check(
            "ck_itinerary_items__kind_enum",
            "kind",
            ["activity", "meal", "transit", "lodging", "note", "free_time"],
        ),
        _check("ck_itinerary_items__origin_enum", "origin", ["user", "ai"]),
        _ck("ck_itinerary_items__duration_range", "duration_minutes BETWEEN 0 AND 1440"),
        _ck("ck_itinerary_items__title_length", "char_length(title) BETWEEN 1 AND 120"),
        _fk("itinerary_items", "day_id", "itinerary_days", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_itinerary_items"),
    )
    op.create_index("ix_itinerary_items__day_order", "itinerary_items", ["day_id", "sort_order"])


def downgrade() -> None:
    for table in (
        "itinerary_items",
        "itinerary_days",
        "trip_collaborators",
        "trip_destinations",
        "trips",
    ):
        op.drop_table(table)
