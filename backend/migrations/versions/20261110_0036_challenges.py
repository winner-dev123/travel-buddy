"""Group challenges: challenges, answers, hints, rewards, badges, participants, submissions,
winners (BL-5.01..5.03; CHAL-001..015).

Revision ID: 0036
Revises: 0035
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036"
down_revision: str | None = "0035"
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
        "group_challenges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.Text(), server_default=sa.text("'riddle'"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("media_asset_id", sa.Uuid(), nullable=True),
        sa.Column("solving_mode", sa.Text(), nullable=False),
        sa.Column("validation_method", sa.Text(), nullable=False),
        sa.Column("normalization", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("max_attempts", sa.SmallInteger(), nullable=False),
        sa.Column(
            "attempt_cooldown_seconds", sa.Integer(), server_default=sa.text("30"), nullable=False
        ),
        sa.Column("winner_policy", sa.Text(), nullable=False),
        sa.Column("max_winners", sa.SmallInteger(), server_default=sa.text("1"), nullable=False),
        sa.Column("prize_description", sa.Text(), nullable=True),
        sa.Column("participation_rules", sa.Text(), nullable=True),
        _ts("starts_at", nullable=False),
        _ts("ends_at", nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        _ts("published_at"),
        _ts("results_published_at"),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("rules_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        _ts("created_at", nullable=False, now=True),
        _ts("updated_at", nullable=False, now=True),
        _check("ck_group_challenges__kind_enum", "kind", ["riddle"]),
        _check(
            "ck_group_challenges__status_enum",
            "status",
            ["draft", "scheduled", "active", "judging", "completed", "cancelled"],
        ),
        _check("ck_group_challenges__solving_mode_enum", "solving_mode", ["individual", "team"]),
        _check(
            "ck_group_challenges__validation_method_enum",
            "validation_method",
            ["exact", "admin_review", "ai_assisted"],
        ),
        _check(
            "ck_group_challenges__winner_policy_enum",
            "winner_policy",
            ["first_correct", "first_n_correct", "all_correct", "admin_selects"],
        ),
        _ck("ck_group_challenges__window", "starts_at < ends_at"),
        _ck("ck_group_challenges__max_attempts_range", "max_attempts BETWEEN 1 AND 20"),
        _ck("ck_group_challenges__max_winners_range", "max_winners BETWEEN 1 AND 50"),
        _fk("group_challenges", "group_id", "travel_groups", "CASCADE"),
        _fk("group_challenges", "created_by", "users", "SET NULL"),
        _fk("group_challenges", "media_asset_id", "media_assets", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_group_challenges"),
    )
    op.create_index(
        "ix_group_challenges__group_status",
        "group_challenges",
        ["group_id", "status", "starts_at"],
    )
    op.create_index(
        "ix_group_challenges__scheduled",
        "group_challenges",
        ["status", "starts_at"],
        postgresql_where=sa.text("status = 'scheduled'"),
    )
    op.create_index(
        "ix_group_challenges__active",
        "group_challenges",
        ["status", "ends_at"],
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "challenge_answers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("challenge_id", sa.Uuid(), nullable=False),
        sa.Column("answer_display", sa.Text(), nullable=False),
        sa.Column("answer_normalized", sa.Text(), nullable=False),
        _ts("created_at", nullable=False, now=True),
        _fk("challenge_answers", "challenge_id", "group_challenges", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_challenge_answers"),
        sa.UniqueConstraint(
            "challenge_id",
            "answer_normalized",
            name="uq_challenge_answers__challenge_id_answer_normalized",
        ),
    )

    op.create_table(
        "challenge_hints",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("challenge_id", sa.Uuid(), nullable=False),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        _ts("release_at"),
        _ck("ck_challenge_hints__body_length", "char_length(body) BETWEEN 1 AND 500"),
        _fk("challenge_hints", "challenge_id", "group_challenges", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_challenge_hints"),
        sa.UniqueConstraint(
            "challenge_id", "sort_order", name="uq_challenge_hints__challenge_id_sort_order"
        ),
    )

    op.create_table(
        "badges",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("icon_media_id", sa.Uuid(), nullable=True),
        _ts("created_at", nullable=False, now=True),
        _fk("badges", "icon_media_id", "media_assets", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_badges"),
        sa.UniqueConstraint("key", name="uq_badges__key"),
    )

    op.create_table(
        "user_badges",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("badge_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        _ts("awarded_at", nullable=False, now=True),
        _check("ck_user_badges__source_type_enum", "source_type", ["challenge", "platform"]),
        _fk("user_badges", "user_id", "users", "CASCADE"),
        _fk("user_badges", "badge_id", "badges", "CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "badge_id", "source_id", name="pk_user_badges"),
    )

    op.create_table(
        "challenge_rewards",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("challenge_id", sa.Uuid(), nullable=False),
        sa.Column("reward_type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("badge_id", sa.Uuid(), nullable=True),
        sa.Column("sponsor_name", sa.Text(), nullable=True),
        sa.Column("quantity", sa.SmallInteger(), nullable=False),
        sa.Column("eligibility_rules", sa.Text(), nullable=True),
        sa.Column("terms_url", sa.Text(), nullable=True),
        sa.Column("fulfillment_owner", sa.Text(), nullable=False),
        sa.Column(
            "requires_platform_review",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "review_status", sa.Text(), server_default=sa.text("'not_required'"), nullable=False
        ),
        _ts("created_at", nullable=False, now=True),
        _check(
            "ck_challenge_rewards__reward_type_enum",
            "reward_type",
            ["badge", "achievement", "discount_code", "promotional"],
        ),
        _check(
            "ck_challenge_rewards__fulfillment_owner_enum",
            "fulfillment_owner",
            ["platform", "group_admin", "sponsor"],
        ),
        _check(
            "ck_challenge_rewards__review_status_enum",
            "review_status",
            ["not_required", "pending", "approved", "rejected"],
        ),
        _ck("ck_challenge_rewards__quantity_range", "quantity BETWEEN 1 AND 100"),
        _fk("challenge_rewards", "challenge_id", "group_challenges", "CASCADE"),
        _fk("challenge_rewards", "badge_id", "badges", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_challenge_rewards"),
    )

    op.create_table(
        "challenge_participants",
        sa.Column("challenge_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("team_id", sa.Uuid(), nullable=True),
        _ts("joined_at", nullable=False, now=True),
        sa.Column("attempts_used", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        _ts("last_attempt_at"),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        _check(
            "ck_challenge_participants__status_enum",
            "status",
            ["active", "disqualified", "withdrawn"],
        ),
        _fk("challenge_participants", "challenge_id", "group_challenges", "CASCADE"),
        _fk("challenge_participants", "user_id", "users", "CASCADE"),
        sa.PrimaryKeyConstraint("challenge_id", "user_id", name="pk_challenge_participants"),
    )

    op.create_table(
        "challenge_submissions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("challenge_id", sa.Uuid(), nullable=False),
        sa.Column("submitted_by", sa.Uuid(), nullable=True),
        sa.Column("team_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_no", sa.SmallInteger(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("answer_normalized", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Uuid(), nullable=False),
        sa.Column(
            "evaluation_status", sa.Text(), server_default=sa.text("'pending'"), nullable=False
        ),
        sa.Column("evaluator", sa.Text(), nullable=True),
        sa.Column("evaluated_by", sa.Uuid(), nullable=True),
        sa.Column("ai_confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("ai_rationale", sa.Text(), nullable=True),
        sa.Column("rules_version", sa.Integer(), nullable=False),
        _ts("submitted_at", nullable=False, now=True),
        _ts("evaluated_at"),
        _check(
            "ck_challenge_submissions__evaluation_status_enum",
            "evaluation_status",
            ["pending", "correct", "incorrect", "needs_review", "void"],
        ),
        _check("ck_challenge_submissions__evaluator_enum", "evaluator", ["exact", "ai", "admin"]),
        _fk("challenge_submissions", "challenge_id", "group_challenges", "CASCADE"),
        _fk("challenge_submissions", "submitted_by", "users", "SET NULL"),
        _fk("challenge_submissions", "evaluated_by", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_challenge_submissions"),
        sa.UniqueConstraint(
            "challenge_id",
            "submitted_by",
            "idempotency_key",
            name="uq_challenge_submissions__idempotency",
        ),
    )
    op.create_index(
        "ix_challenge_submissions__challenge_time",
        "challenge_submissions",
        ["challenge_id", "submitted_at"],
    )

    op.create_table(
        "challenge_winners",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("challenge_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("team_id", sa.Uuid(), nullable=True),
        sa.Column("submission_id", sa.Uuid(), nullable=False),
        sa.Column("rank", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'provisional'"), nullable=False),
        sa.Column("determined_by", sa.Text(), server_default=sa.text("'system'"), nullable=False),
        _ts("determined_at", nullable=False, now=True),
        sa.Column("confirmed_by", sa.Uuid(), nullable=True),
        _check(
            "ck_challenge_winners__status_enum", "status", ["provisional", "confirmed", "revoked"]
        ),
        _check("ck_challenge_winners__determined_by_enum", "determined_by", ["system", "admin"]),
        _ck("ck_challenge_winners__one_recipient", "(user_id IS NULL) <> (team_id IS NULL)"),
        _fk("challenge_winners", "challenge_id", "group_challenges", "CASCADE"),
        _fk("challenge_winners", "user_id", "users", "SET NULL"),
        _fk("challenge_winners", "submission_id", "challenge_submissions", "CASCADE"),
        _fk("challenge_winners", "confirmed_by", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_challenge_winners"),
    )
    op.create_index(
        "uq_challenge_winners__rank",
        "challenge_winners",
        ["challenge_id", "rank"],
        unique=True,
        postgresql_where=sa.text("status <> 'revoked'"),
    )


def downgrade() -> None:
    for table in (
        "challenge_winners",
        "challenge_submissions",
        "challenge_participants",
        "challenge_rewards",
        "user_badges",
        "badges",
        "challenge_hints",
        "challenge_answers",
        "group_challenges",
    ):
        op.drop_table(table)
