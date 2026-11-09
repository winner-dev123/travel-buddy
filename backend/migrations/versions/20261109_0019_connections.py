"""Connection requests and connections (BL-2.04).

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _check(name: str, column: str, values: Sequence[str]) -> sa.CheckConstraint:
    """``op.f``: ``name`` is final, so the naming convention does not prefix it again."""
    allowed = ", ".join(f"'{v}'" for v in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=op.f(name))


def upgrade() -> None:
    op.create_table(
        "connection_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("requester_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("context", sa.Text(), nullable=False),
        sa.Column("context_ref_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _check(
            "ck_connection_requests__status_enum",
            "status",
            ["pending", "accepted", "declined", "cancelled", "expired"],
        ),
        _check(
            "ck_connection_requests__context_enum",
            "context",
            ["discovery", "group", "profile", "post"],
        ),
        sa.CheckConstraint(
            "requester_id <> recipient_id", name=op.f("ck_connection_requests__not_self")
        ),
        sa.CheckConstraint(
            "char_length(note) <= 140", name=op.f("ck_connection_requests__note_length")
        ),
        sa.ForeignKeyConstraint(
            ["requester_id"],
            ["users.id"],
            name="fk_connection_requests__requester_id__users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["users.id"],
            name="fk_connection_requests__recipient_id__users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_connection_requests"),
    )
    op.create_index(
        "uq_connection_requests__pending_pair",
        "connection_requests",
        ["requester_id", "recipient_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_connection_requests__inbox",
        "connection_requests",
        ["recipient_id", "status", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_connection_requests__outbox",
        "connection_requests",
        ["requester_id", "status", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_connection_requests__pair_responded",
        "connection_requests",
        ["requester_id", "recipient_id", sa.text("responded_at DESC")],
    )
    op.create_table(
        "user_connections",
        sa.Column("user_low_id", sa.Uuid(), nullable=False),
        sa.Column("user_high_id", sa.Uuid(), nullable=False),
        sa.Column("source_request_id", sa.Uuid(), nullable=True),
        sa.Column(
            "connected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("user_low_id < user_high_id", name=op.f("ck_user_connections__ordered")),
        sa.ForeignKeyConstraint(
            ["user_low_id"],
            ["users.id"],
            name="fk_user_connections__user_low_id__users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_high_id"],
            ["users.id"],
            name="fk_user_connections__user_high_id__users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_request_id"],
            ["connection_requests.id"],
            name="fk_user_connections__source_request_id__connection_requests",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("user_low_id", "user_high_id", name="pk_user_connections"),
    )
    op.create_index("ix_user_connections__user_high_id", "user_connections", ["user_high_id"])


def downgrade() -> None:
    op.drop_table("user_connections")
    op.drop_table("connection_requests")
