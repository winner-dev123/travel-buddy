"""Challenge teams: captain, team thread, team attempts (BL-5.04; CHAL-004).

Revision ID: 0037
Revises: 0036
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0037"
down_revision: str | None = "0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _ck(name: str, condition: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(condition, name=op.f(name))


def _fk(table: str, column: str, referred: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column], [f"{referred}.id"], name=f"fk_{table}__{column}__{referred}", ondelete=ondelete
    )


def upgrade() -> None:
    op.create_table(
        "challenge_teams",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("challenge_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("captain_id", sa.Uuid(), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("attempts_used", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        _ck("ck_challenge_teams__name_length", "char_length(name) BETWEEN 2 AND 40"),
        _fk("challenge_teams", "challenge_id", "group_challenges", "CASCADE"),
        _fk("challenge_teams", "captain_id", "users", "SET NULL"),
        _fk("challenge_teams", "conversation_id", "conversations", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_challenge_teams"),
        sa.UniqueConstraint("challenge_id", "name", name="uq_challenge_teams__challenge_id_name"),
    )
    op.create_foreign_key(
        "fk_challenge_participants__team_id__challenge_teams",
        "challenge_participants",
        "challenge_teams",
        ["team_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_challenge_participants__team_id", "challenge_participants", ["team_id"], unique=False
    )
    op.create_foreign_key(
        "fk_challenge_submissions__team_id__challenge_teams",
        "challenge_submissions",
        "challenge_teams",
        ["team_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_challenge_winners__team_id__challenge_teams",
        "challenge_winners",
        "challenge_teams",
        ["team_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_conversations__challenge_team_id__challenge_teams",
        "conversations",
        "challenge_teams",
        ["challenge_team_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_conversations__challenge_team_id__challenge_teams", "conversations", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_challenge_winners__team_id__challenge_teams", "challenge_winners", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_challenge_submissions__team_id__challenge_teams",
        "challenge_submissions",
        type_="foreignkey",
    )
    op.drop_index("ix_challenge_participants__team_id", table_name="challenge_participants")
    op.drop_constraint(
        "fk_challenge_participants__team_id__challenge_teams",
        "challenge_participants",
        type_="foreignkey",
    )
    op.drop_table("challenge_teams")
