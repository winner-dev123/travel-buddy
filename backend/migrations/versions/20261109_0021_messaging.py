"""Conversations and messages (BL-3.03; docs/04 §7).

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ck(name: str, condition: str) -> sa.CheckConstraint:
    """``op.f``: ``name`` is final, so the naming convention does not prefix it again."""
    return sa.CheckConstraint(condition, name=op.f(name))


def _check(name: str, column: str, values: Sequence[str]) -> sa.CheckConstraint:
    allowed = ", ".join(f"'{v}'" for v in values)
    return _ck(name, f"{column} IN ({allowed})")


def _fk(
    table: str, column: str, referred: str, ondelete: str, name: str | None = None
) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column],
        [f"{referred}.id"],
        name=name or f"fk_{table}__{column}__{referred}",
        ondelete=ondelete,
    )


def _now() -> sa.Column[sa.DateTime]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("direct_key", sa.Text(), nullable=True),
        sa.Column("group_id", sa.Uuid(), nullable=True),
        sa.Column("challenge_team_id", sa.Uuid(), nullable=True),
        sa.Column("last_seq", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        _now(),
        _check("ck_conversations__kind_enum", "kind", ["direct", "group", "challenge_team"]),
        _ck(
            "ck_conversations__target_per_kind",
            "(kind = 'direct' AND direct_key IS NOT NULL AND group_id IS NULL "
            "AND challenge_team_id IS NULL) "
            "OR (kind = 'group' AND group_id IS NOT NULL AND direct_key IS NULL "
            "AND challenge_team_id IS NULL) "
            "OR (kind = 'challenge_team' AND challenge_team_id IS NOT NULL "
            "AND direct_key IS NULL AND group_id IS NULL)",
        ),
        _ck("ck_conversations__last_seq_nonnegative", "last_seq >= 0"),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
        sa.UniqueConstraint("direct_key", name="uq_conversations__direct_key"),
    )
    op.create_index(
        "uq_conversations__group_id",
        "conversations",
        ["group_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'group'"),
    )

    op.create_table(
        "conversation_members",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("joined_at_seq", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("muted_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notification_level", sa.Text(), server_default=sa.text("'all'"), nullable=False),
        sa.Column(
            "cleared_through_seq", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        _check(
            "ck_conversation_members__notification_level_enum",
            "notification_level",
            ["all", "mentions", "none"],
        ),
        _fk("conversation_members", "conversation_id", "conversations", "CASCADE"),
        _fk("conversation_members", "user_id", "users", "CASCADE"),
        sa.PrimaryKeyConstraint("conversation_id", "user_id", name="pk_conversation_members"),
    )
    op.create_index(
        "ix_conversation_members__active_user",
        "conversation_members",
        ["user_id"],
        postgresql_where=sa.text("left_at IS NULL"),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("sender_id", sa.Uuid(), nullable=True),
        sa.Column("client_message_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.Text(), server_default=sa.text("'text'"), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("reply_to_message_id", sa.Uuid(), nullable=True),
        sa.Column("thread_root_id", sa.Uuid(), nullable=True),
        sa.Column(
            "moderation_state", sa.Text(), server_default=sa.text("'visible'"), nullable=False
        ),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Uuid(), nullable=True),
        _now(),
        _check("ck_messages__kind_enum", "kind", ["text", "image", "system", "announcement"]),
        _check(
            "ck_messages__moderation_state_enum",
            "moderation_state",
            ["visible", "removed_by_moderator", "removed_by_admin"],
        ),
        _ck("ck_messages__seq_positive", "seq >= 1"),
        _ck("ck_messages__body_length", "char_length(body) <= 4000"),
        _fk("messages", "conversation_id", "conversations", "CASCADE"),
        _fk("messages", "sender_id", "users", "SET NULL"),
        _fk("messages", "reply_to_message_id", "messages", "SET NULL"),
        _fk("messages", "thread_root_id", "messages", "SET NULL"),
        _fk("messages", "deleted_by", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
        sa.UniqueConstraint("conversation_id", "seq", name="uq_messages__conversation_id_seq"),
        sa.UniqueConstraint(
            "conversation_id",
            "sender_id",
            "client_message_id",
            name="uq_messages__conversation_id_sender_id_client_message_id",
        ),
    )
    op.create_index(
        "ix_messages__thread",
        "messages",
        ["thread_root_id", "seq"],
        postgresql_where=sa.text("thread_root_id IS NOT NULL"),
    )
    op.create_index("ix_messages__sender_id", "messages", ["sender_id"])
    op.create_index(
        "ix_messages__orphaned",
        "messages",
        ["id"],
        postgresql_where=sa.text(
            "sender_id IS NULL AND deleted_at IS NULL AND kind IN ('text', 'image')"
        ),
    )

    op.create_table(
        "message_attachments",
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("media_asset_id", sa.Uuid(), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        _fk("message_attachments", "message_id", "messages", "CASCADE"),
        _fk("message_attachments", "media_asset_id", "media_assets", "CASCADE"),
        sa.PrimaryKeyConstraint("message_id", "media_asset_id", name="pk_message_attachments"),
    )
    op.create_index(
        "ix_message_attachments__media_asset_id", "message_attachments", ["media_asset_id"]
    )

    op.create_table(
        "message_receipts",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "delivered_through_seq", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("read_through_seq", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        _fk("message_receipts", "conversation_id", "conversations", "CASCADE"),
        _fk("message_receipts", "user_id", "users", "CASCADE"),
        sa.PrimaryKeyConstraint("conversation_id", "user_id", name="pk_message_receipts"),
    )

    op.create_table(
        "message_reactions",
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("emoji", sa.Text(), nullable=False),
        _now(),
        _ck("ck_message_reactions__emoji_length", "octet_length(emoji) <= 16"),
        _fk("message_reactions", "message_id", "messages", "CASCADE"),
        _fk("message_reactions", "user_id", "users", "CASCADE"),
        sa.PrimaryKeyConstraint("message_id", "user_id", "emoji", name="pk_message_reactions"),
    )

    op.create_table(
        "message_mentions",
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        _fk("message_mentions", "message_id", "messages", "CASCADE"),
        _fk("message_mentions", "user_id", "users", "CASCADE"),
        sa.PrimaryKeyConstraint("message_id", "user_id", name="pk_message_mentions"),
    )
    op.create_index(
        "ix_message_mentions__user",
        "message_mentions",
        ["user_id", sa.text("message_id DESC")],
    )

    op.create_table(
        "conversation_pins",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("pinned_by", sa.Uuid(), nullable=True),
        sa.Column(
            "pinned_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        _fk("conversation_pins", "conversation_id", "conversations", "CASCADE"),
        _fk("conversation_pins", "message_id", "messages", "CASCADE"),
        _fk("conversation_pins", "pinned_by", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("conversation_id", "message_id", name="pk_conversation_pins"),
    )
    op.create_index("ix_conversation_pins__message_id", "conversation_pins", ["message_id"])


def downgrade() -> None:
    for table in (
        "conversation_pins",
        "message_mentions",
        "message_reactions",
        "message_receipts",
        "message_attachments",
        "messages",
        "conversation_members",
        "conversations",
    ):
        op.drop_table(table)
