"""Challenge results: reward fulfillments and disputes (BL-5.06, BL-5.07; CHAL-011, CHAL-015,
CHAL-016).

Revision ID: 0038
Revises: 0037
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0038"
down_revision: str | None = "0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _check(name: str, column: str, values: Sequence[str]) -> sa.CheckConstraint:
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
        "reward_fulfillments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("challenge_id", sa.Uuid(), nullable=False),
        sa.Column("challenge_reward_id", sa.Uuid(), nullable=False),
        sa.Column("winner_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_user_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("secret_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("issued_by", sa.Uuid(), nullable=True),
        _ts("issued_at"),
        _ts("delivered_at"),
        sa.Column("notes", sa.Text(), nullable=True),
        _ts("created_at", nullable=False, now=True),
        _ts("updated_at", nullable=False, now=True),
        _check(
            "ck_reward_fulfillments__status_enum",
            "status",
            ["pending", "issued", "delivered", "failed", "cancelled", "disputed"],
        ),
        _fk("reward_fulfillments", "challenge_id", "group_challenges", "CASCADE"),
        _fk("reward_fulfillments", "challenge_reward_id", "challenge_rewards", "CASCADE"),
        _fk("reward_fulfillments", "winner_id", "challenge_winners", "CASCADE"),
        _fk("reward_fulfillments", "recipient_user_id", "users", "SET NULL"),
        _fk("reward_fulfillments", "issued_by", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_reward_fulfillments"),
        sa.UniqueConstraint(
            "challenge_reward_id",
            "winner_id",
            name="uq_reward_fulfillments__challenge_reward_id_winner_id",
        ),
    )
    op.create_index(
        "ix_reward_fulfillments__recipient",
        "reward_fulfillments",
        ["recipient_user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_reward_fulfillments__challenge",
        "reward_fulfillments",
        ["challenge_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "challenge_disputes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("challenge_id", sa.Uuid(), nullable=False),
        sa.Column("raised_by", sa.Uuid(), nullable=True),
        sa.Column("submission_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'open'"), nullable=False),
        sa.Column("resolved_by", sa.Uuid(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        _ts("created_at", nullable=False, now=True),
        _ts("resolved_at"),
        _check("ck_challenge_disputes__status_enum", "status", ["open", "upheld", "rejected"]),
        _ck("ck_challenge_disputes__reason_length", "char_length(reason) BETWEEN 10 AND 1000"),
        _fk("challenge_disputes", "challenge_id", "group_challenges", "CASCADE"),
        _fk("challenge_disputes", "raised_by", "users", "SET NULL"),
        _fk("challenge_disputes", "submission_id", "challenge_submissions", "SET NULL"),
        _fk("challenge_disputes", "resolved_by", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_challenge_disputes"),
    )
    op.create_index(
        "ix_challenge_disputes__challenge",
        "challenge_disputes",
        ["challenge_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_challenge_disputes__challenge", table_name="challenge_disputes")
    op.drop_table("challenge_disputes")
    op.drop_index("ix_reward_fulfillments__challenge", table_name="reward_fulfillments")
    op.drop_index("ix_reward_fulfillments__recipient", table_name="reward_fulfillments")
    op.drop_table("reward_fulfillments")
