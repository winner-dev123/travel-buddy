"""Trust and safety: content reports, moderation actions, timed suspensions (BL-1.14).

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("now()")


def _check(name: str, column: str, values: Sequence[str]) -> sa.CheckConstraint:
    allowed = ", ".join(f"'{v}'" for v in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=name)


def _user_fk(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], ["users.id"], name=f"fk_{table}__{column}__users", ondelete="SET NULL"
    )


def upgrade() -> None:
    op.add_column("users", sa.Column("suspended_until", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "content_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reporter_id", sa.Uuid(), nullable=True),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("target_author_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("priority", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'open'"), nullable=False),
        sa.Column("assigned_to", sa.Uuid(), nullable=True),
        sa.Column("evidence", postgresql.JSONB(), nullable=False),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('open', 'in_review', 'actioned', 'dismissed')",
            name="ck_content_reports__status_enum",
        ),
        _check(
            "ck_content_reports__reason_enum",
            "reason",
            [
                "spam",
                "harassment",
                "hate",
                "sexual_content",
                "minor_safety",
                "violence",
                "self_harm",
                "scam",
                "privacy_violation",
                "impersonation",
                "illegal",
                "other",
            ],
        ),
        _check(
            "ck_content_reports__target_type_enum",
            "target_type",
            ["post", "comment", "user", "message", "group", "challenge", "media"],
        ),
        _user_fk("content_reports", "reporter_id"),
        _user_fk("content_reports", "assigned_to"),
        _user_fk("content_reports", "resolved_by"),
        sa.PrimaryKeyConstraint("id", name="pk_content_reports"),
    )
    op.create_index(
        "ix_content_reports__queue",
        "content_reports",
        ["status", sa.text("priority DESC"), "created_at"],
    )
    op.create_index("ix_content_reports__target", "content_reports", ["target_type", "target_id"])
    op.create_index("ix_content_reports__target_author", "content_reports", ["target_author_id"])
    op.create_index(
        "uq_content_reports__open_per_reporter",
        "content_reports",
        ["reporter_id", "target_type", "target_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('open', 'in_review')"),
    )

    op.create_table(
        "moderation_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.Text(), server_default=sa.text("'platform'"), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("report_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        _check(
            "ck_moderation_actions__action_enum",
            "action",
            [
                "remove_content",
                "restore_content",
                "limit_visibility",
                "warn",
                "restrict",
                "suspend",
                "ban",
                "reinstate",
                "remove_member",
            ],
        ),
        _check(
            "ck_moderation_actions__target_type_enum",
            "target_type",
            ["post", "comment", "user", "message", "group", "challenge", "media"],
        ),
        sa.CheckConstraint(
            "scope IN ('platform', 'group')", name="ck_moderation_actions__scope_enum"
        ),
        _user_fk("moderation_actions", "actor_id"),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["content_reports.id"],
            name="fk_moderation_actions__report_id__content_reports",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_moderation_actions"),
    )
    op.create_index(
        "ix_moderation_actions__target",
        "moderation_actions",
        ["target_type", "target_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_table("moderation_actions")
    op.drop_table("content_reports")
    op.drop_column("users", "suspended_until")
