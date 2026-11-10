"""Push device registry and quiet hours (BL-3.06; docs/04 §3, NOTIF-002/003/005).

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _check(name: str, column: str, values: Sequence[str]) -> sa.CheckConstraint:
    """``op.f``: ``name`` is final, so the naming convention does not prefix it again."""
    allowed = ", ".join(f"'{v}'" for v in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=op.f(name))


def upgrade() -> None:
    op.create_table(
        "device_push_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("token_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("webpush_p256dh", sa.LargeBinary(), nullable=True),
        sa.Column("webpush_auth", sa.LargeBinary(), nullable=True),
        sa.Column("device_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        _check(
            "ck_device_push_tokens__provider_enum",
            "provider",
            ["expo", "fcm", "apns", "webpush"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_device_push_tokens__user_id__users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["user_sessions.id"],
            name="fk_device_push_tokens__session_id__user_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_device_push_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_device_push_tokens__token_hash"),
    )
    op.create_index("ix_device_push_tokens__user_id", "device_push_tokens", ["user_id"])
    op.create_index("ix_device_push_tokens__session_id", "device_push_tokens", ["session_id"])
    op.add_column(
        "user_preferences",
        sa.Column("quiet_hours", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_preferences", "quiet_hours")
    op.drop_table("device_push_tokens")
