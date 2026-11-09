"""Baseline: extensions + platform tables (outbox, jobs, idempotency, audit).

Revision ID: 0001
Revises:
Create Date: 2026-11-09

Phase 0 migration (docs/04 section 15). Domain tables arrive with their phases.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for extension in ("postgis", "citext", "pg_trgm", "unaccent"):
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {extension}")

    # unaccent() is STABLE; an IMMUTABLE wrapper is required for expression indexes used by
    # accent-insensitive destination search (DEST-001).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION f_unaccent(text) RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
        AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$
        """
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_events"),
    )
    op.create_index(
        "ix_outbox_events__unpublished",
        "outbox_events",
        ["id"],
        postgresql_where=sa.text("published_at IS NULL"),
    )

    op.create_table(
        "asynchronous_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("queue", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column("priority", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("10"), nullable=False),
        sa.Column(
            "run_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("dedupe_key", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'dead')",
            name="ck_asynchronous_jobs__status_enum",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_asynchronous_jobs"),
    )
    op.create_index(
        "ix_asynchronous_jobs__claimable",
        "asynchronous_jobs",
        ["queue", sa.text("priority DESC"), "run_at"],
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_index(
        "uq_asynchronous_jobs__active_dedupe_key",
        "asynchronous_jobs",
        ["dedupe_key"],
        unique=True,
        postgresql_where=sa.text("dedupe_key IS NOT NULL AND status IN ('queued', 'running')"),
    )

    op.create_table(
        "idempotency_keys",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.Uuid(), nullable=False),
        sa.Column("route", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'in_progress'"), nullable=False),
        sa.Column("response_status", sa.SmallInteger(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('in_progress', 'completed')", name="ck_idempotency_keys__status_enum"
        ),
        sa.PrimaryKeyConstraint("user_id", "key", name="pk_idempotency_keys"),
    )
    op.create_index("ix_idempotency_keys__expires_at", "idempotency_keys", ["expires_at"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("resource_type", sa.Text(), nullable=False),
        sa.Column("resource_id", sa.Text(), nullable=False),
        sa.Column("scope_group_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.CheckConstraint(
            "actor_type IN ('user', 'admin', 'system', 'service')",
            name="ck_audit_logs__actor_type_enum",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
    )
    op.create_index(
        "ix_audit_logs__resource",
        "audit_logs",
        ["resource_type", "resource_id", sa.text("occurred_at DESC")],
    )
    op.create_index("ix_audit_logs__actor", "audit_logs", ["actor_id", sa.text("occurred_at DESC")])

    # Append-only enforcement independent of database role grants (SAFE-007, T-OPS-04).
    # Retention purges in Phase 6 use partition DROP, which this trigger does not block.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_logs_block_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'audit_logs is append-only (% blocked)', TG_OP
            USING ERRCODE = 'insufficient_privilege';
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_logs_append_only
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION audit_logs_block_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_logs_no_truncate
        BEFORE TRUNCATE ON audit_logs
        FOR EACH STATEMENT EXECUTE FUNCTION audit_logs_block_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_logs_no_truncate ON audit_logs")
    op.execute("DROP TRIGGER IF EXISTS audit_logs_append_only ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS audit_logs_block_mutation()")
    op.drop_table("audit_logs")
    op.drop_table("idempotency_keys")
    op.drop_table("asynchronous_jobs")
    op.drop_table("outbox_events")
    op.execute("DROP FUNCTION IF EXISTS f_unaccent(text)")
    # Extensions are left installed: they may be shared with other schemas.
