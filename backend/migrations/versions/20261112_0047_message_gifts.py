"""Gifts in direct chats (DM-016): ``messages.gift_code`` and ``messages.gift_opened_at``.

A gift is a message of kind ``gift`` naming one present from the app's catalog. The catalog is
checked by the API, not here, so a new present needs only an app release. Gifts of deleted
accounts are tombstoned by the retention job like text and photos, so its partial index now
covers them too.

Revision ID: 0047
Revises: 0046
Create Date: 2026-11-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _check(name: str, column: str, values: Sequence[str]) -> sa.CheckConstraint:
    allowed = ", ".join(f"'{v}'" for v in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=op.f(name))


def _replace_kinds(kinds: sa.CheckConstraint) -> None:
    op.execute("ALTER TABLE messages DROP CONSTRAINT ck_messages__kind_enum")
    op.execute(
        f"ALTER TABLE messages ADD CONSTRAINT ck_messages__kind_enum CHECK ({kinds.sqltext})"
    )


def _orphaned_index(kinds: str) -> None:
    op.create_index(
        "ix_messages__orphaned",
        "messages",
        ["id"],
        postgresql_where=sa.text(f"sender_id IS NULL AND deleted_at IS NULL AND kind IN ({kinds})"),
    )


def upgrade() -> None:
    op.add_column("messages", sa.Column("gift_code", sa.Text(), nullable=True))
    op.add_column(
        "messages", sa.Column("gift_opened_at", sa.DateTime(timezone=True), nullable=True)
    )
    _replace_kinds(
        _check(
            "ck_messages__kind_enum",
            "kind",
            ["text", "image", "system", "announcement", "gift"],
        )
    )
    op.create_check_constraint(
        op.f("ck_messages__gift_code_per_kind"),
        "messages",
        "(kind = 'gift') = (gift_code IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_messages__gift_code_length"), "messages", "char_length(gift_code) <= 32"
    )
    op.create_check_constraint(
        op.f("ck_messages__gift_opened_per_kind"),
        "messages",
        "gift_opened_at IS NULL OR kind = 'gift'",
    )
    op.drop_index("ix_messages__orphaned", table_name="messages")
    _orphaned_index("'text', 'image', 'gift'")


def downgrade() -> None:
    # Gifts can't be represented without these columns; they are removed with them.
    op.execute("DELETE FROM messages WHERE kind = 'gift'")
    op.drop_index("ix_messages__orphaned", table_name="messages")
    _orphaned_index("'text', 'image'")
    for name in ("gift_opened_per_kind", "gift_code_length", "gift_code_per_kind"):
        op.drop_constraint(op.f(f"ck_messages__{name}"), "messages", type_="check")
    # Downgrade text only (the static schema check reads the last `_check` above as current).
    op.execute("ALTER TABLE messages DROP CONSTRAINT ck_messages__kind_enum")
    op.execute(
        "ALTER TABLE messages ADD CONSTRAINT ck_messages__kind_enum "
        "CHECK (kind IN ('text', 'image', 'system', 'announcement'))"
    )
    op.drop_column("messages", "gift_opened_at")
    op.drop_column("messages", "gift_code")
