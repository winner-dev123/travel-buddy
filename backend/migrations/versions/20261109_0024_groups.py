"""Travel groups: groups, settings, memberships, invitations, ownership transfers (BL-3.07..3.10).

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | None = "0023"
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


def _fk(
    table: str, column: str, referred: str, ondelete: str, name: str | None = None
) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column],
        [f"{referred}.id"],
        name=name or f"fk_{table}__{column}__{referred}",
        ondelete=ondelete,
    )


def upgrade() -> None:
    op.create_table(
        "travel_groups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("cover_media_id", sa.Uuid(), nullable=True),
        sa.Column("primary_destination_id", sa.Uuid(), nullable=False),
        sa.Column("trip_id", sa.Uuid(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("visibility", sa.Text(), server_default=sa.text("'private'"), nullable=False),
        sa.Column(
            "join_policy", sa.Text(), server_default=sa.text("'invite_only'"), nullable=False
        ),
        sa.Column("member_capacity", sa.Integer(), server_default=sa.text("20"), nullable=False),
        sa.Column(
            "interests", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        _ts("created_at", nullable=False, now=True),
        _ts("updated_at", nullable=False, now=True),
        _ts("archived_at"),
        _check(
            "ck_travel_groups__visibility_enum", "visibility", ["private", "unlisted", "public"]
        ),
        _check(
            "ck_travel_groups__join_policy_enum", "join_policy", ["invite_only", "request_to_join"]
        ),
        _check("ck_travel_groups__status_enum", "status", ["active", "archived", "suspended"]),
        _ck("ck_travel_groups__name_length", "char_length(name) BETWEEN 3 AND 60"),
        _ck("ck_travel_groups__capacity_range", "member_capacity BETWEEN 2 AND 50"),
        _ck(
            "ck_travel_groups__dates_order",
            "start_date IS NULL OR end_date IS NULL OR start_date <= end_date",
        ),
        _fk("travel_groups", "cover_media_id", "media_assets", "SET NULL"),
        _fk(
            "travel_groups",
            "primary_destination_id",
            "destinations",
            "RESTRICT",
            name="fk_travel_groups__primary_destination_id__destinations",
        ),
        _fk("travel_groups", "owner_id", "users", "RESTRICT"),
        _fk("travel_groups", "created_by", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_travel_groups"),
    )
    op.create_index(
        "ix_travel_groups__owner_active",
        "travel_groups",
        ["owner_id"],
        postgresql_where=sa.text("status = 'active'"),
    )
    # The group chat (messaging, migration 0021) now has its target table.
    op.create_foreign_key(
        "fk_conversations__group_id__travel_groups",
        "conversations",
        "travel_groups",
        ["group_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.create_table(
        "group_settings",
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column(
            "members_can_invite", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("chat_mode", sa.Text(), server_default=sa.text("'everyone'"), nullable=False),
        sa.Column(
            "new_member_history", sa.Text(), server_default=sa.text("'full'"), nullable=False
        ),
        sa.Column(
            "challenge_defaults",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        _ts("updated_at", nullable=False, now=True),
        _check("ck_group_settings__chat_mode_enum", "chat_mode", ["everyone", "admins_only"]),
        _check("ck_group_settings__history_enum", "new_member_history", ["full", "from_join"]),
        _fk("group_settings", "group_id", "travel_groups", "CASCADE"),
        sa.PrimaryKeyConstraint("group_id", name="pk_group_settings"),
    )

    op.create_table(
        "group_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), server_default=sa.text("'member'"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        _ts("restricted_until"),
        _ts("joined_at", nullable=False, now=True),
        sa.Column("invited_by", sa.Uuid(), nullable=True),
        sa.Column("removed_by", sa.Uuid(), nullable=True),
        _ts("removed_at"),
        sa.Column("removal_reason", sa.Text(), nullable=True),
        _check(
            "ck_group_memberships__role_enum", "role", ["owner", "admin", "moderator", "member"]
        ),
        _check(
            "ck_group_memberships__status_enum",
            "status",
            ["active", "restricted", "removed", "left"],
        ),
        _fk("group_memberships", "group_id", "travel_groups", "CASCADE"),
        _fk("group_memberships", "user_id", "users", "CASCADE"),
        _fk("group_memberships", "invited_by", "users", "SET NULL"),
        _fk("group_memberships", "removed_by", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_group_memberships"),
        sa.UniqueConstraint("group_id", "user_id", name="uq_group_memberships__group_id_user_id"),
    )
    op.create_index("ix_group_memberships__user_status", "group_memberships", ["user_id", "status"])
    op.create_index(
        "uq_group_memberships__owner",
        "group_memberships",
        ["group_id"],
        unique=True,
        postgresql_where=sa.text("role = 'owner' AND status IN ('active', 'restricted')"),
    )

    op.create_table(
        "group_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("invitee_user_id", sa.Uuid(), nullable=True),
        sa.Column("token_hash", sa.LargeBinary(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("max_uses", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("use_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        _ts("expires_at", nullable=False),
        _ts("revoked_at"),
        sa.Column("revoked_by", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        _ts("created_at", nullable=False, now=True),
        _check("ck_group_invitations__kind_enum", "kind", ["direct", "link"]),
        _check(
            "ck_group_invitations__status_enum",
            "status",
            ["active", "exhausted", "revoked", "expired", "accepted", "declined"],
        ),
        _ck("ck_group_invitations__uses_within_max", "use_count <= max_uses"),
        _ck("ck_group_invitations__max_uses_range", "max_uses BETWEEN 1 AND 100"),
        _fk("group_invitations", "group_id", "travel_groups", "CASCADE"),
        _fk("group_invitations", "invitee_user_id", "users", "CASCADE"),
        _fk("group_invitations", "created_by", "users", "SET NULL"),
        _fk("group_invitations", "revoked_by", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_group_invitations"),
        sa.UniqueConstraint("token_hash", name="uq_group_invitations__token_hash"),
    )
    op.create_index(
        "uq_group_invitations__active_direct",
        "group_invitations",
        ["group_id", "invitee_user_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'direct' AND status = 'active'"),
    )
    op.create_index(
        "ix_group_invitations__invitee", "group_invitations", ["invitee_user_id", "status"]
    )

    op.create_table(
        "group_ownership_transfers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("from_user_id", sa.Uuid(), nullable=False),
        sa.Column("to_user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        _ts("created_at", nullable=False, now=True),
        _ts("responded_at"),
        _ts("expires_at", nullable=False),
        _check(
            "ck_group_ownership_transfers__status_enum",
            "status",
            ["pending", "accepted", "declined", "cancelled", "expired"],
        ),
        _fk("group_ownership_transfers", "group_id", "travel_groups", "CASCADE"),
        _fk("group_ownership_transfers", "from_user_id", "users", "CASCADE"),
        _fk("group_ownership_transfers", "to_user_id", "users", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_group_ownership_transfers"),
    )
    op.create_index(
        "uq_group_ownership_transfers__pending",
        "group_ownership_transfers",
        ["group_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_conversations__group_id__travel_groups", "conversations", type_="foreignkey"
    )
    for table in (
        "group_ownership_transfers",
        "group_invitations",
        "group_memberships",
        "group_settings",
        "travel_groups",
    ):
        op.drop_table(table)
