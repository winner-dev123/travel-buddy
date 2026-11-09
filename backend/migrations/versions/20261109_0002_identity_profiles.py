"""Identity and profiles: users, IdP links, sessions, consents, admin roles, profiles.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-09

Phase 1 (BL-1.01..1.04). Defaults are privacy-protective: discovery off, indexing off.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("now()")


def _check(name: str, column: str, values: Sequence[str]) -> sa.CheckConstraint:
    allowed = ", ".join(f"'{v}'" for v in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=name)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=True),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("birth_year", sa.SmallInteger(), nullable=True),
        sa.Column("age_assured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("primary_locale", sa.Text(), nullable=False),
        sa.Column("last_active_on", sa.Date(), nullable=True),
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        _check(
            "ck_users__status_enum",
            "status",
            ["active", "suspended", "deactivated", "pending_deletion", "deleted"],
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_index(
        "uq_users__email_active",
        "users",
        ["email"],
        unique=True,
        postgresql_where=sa.text("email IS NOT NULL AND status <> 'deleted'"),
    )

    op.create_table(
        "authentication_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("email_at_link", postgresql.CITEXT(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        _check(
            "ck_authentication_identities__method_enum",
            "method",
            ["email_password", "apple", "google", "oidc", "dev"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_authentication_identities__user_id__users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_authentication_identities"),
        sa.UniqueConstraint(
            "issuer", "subject", name="uq_authentication_identities__issuer_subject"
        ),
    )
    op.create_index(
        "ix_authentication_identities__user_id", "authentication_identities", ["user_id"]
    )

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("refresh_token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("previous_refresh_token_hash", sa.LargeBinary(), nullable=True),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refresh_generation", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("device_id", sa.Text(), nullable=True),
        sa.Column("device_name", sa.Text(), nullable=True),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("app_version", sa.Text(), nullable=True),
        sa.Column(
            "amr", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("auth_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.Text(), nullable=True),
        sa.Column("last_ip", postgresql.INET(), nullable=True),
        sa.Column("last_admin_activity_at", sa.DateTime(timezone=True), nullable=True),
        _check("ck_user_sessions__platform_enum", "platform", ["ios", "android", "web"]),
        _check(
            "ck_user_sessions__revoked_reason_enum",
            "revoked_reason",
            [
                "logout",
                "user_revoked",
                "reuse_detected",
                "admin",
                "password_changed",
                "account_deleted",
            ],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_sessions__user_id__users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_sessions"),
        sa.UniqueConstraint("refresh_token_hash", name="uq_user_sessions__refresh_token_hash"),
    )
    op.create_index(
        "ix_user_sessions__previous_refresh_token_hash",
        "user_sessions",
        ["previous_refresh_token_hash"],
        postgresql_where=sa.text("previous_refresh_token_hash IS NOT NULL"),
    )
    op.create_index(
        "ix_user_sessions__user_id_active",
        "user_sessions",
        ["user_id"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )

    op.create_table(
        "retired_refresh_tokens",
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["user_sessions.id"],
            name="fk_retired_refresh_tokens__session_id__user_sessions",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("token_hash", name="pk_retired_refresh_tokens"),
    )
    op.create_index(
        "ix_retired_refresh_tokens__session_id", "retired_refresh_tokens", ["session_id"]
    )

    op.create_table(
        "consent_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("consent_type", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        _check(
            "ck_consent_records__consent_type_enum",
            "consent_type",
            [
                "terms",
                "privacy_policy",
                "location",
                "traveler_discovery",
                "marketing",
                "ai_personalization",
                "post_translation",
                "search_indexing",
            ],
        ),
        _check("ck_consent_records__source_enum", "source", ["onboarding", "settings", "prompt"]),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_consent_records__user_id__users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_consent_records"),
    )
    op.create_index(
        "ix_consent_records__user_type_recorded",
        "consent_records",
        ["user_id", "consent_type", sa.text("recorded_at DESC")],
    )

    op.create_table(
        "admin_role_assignments",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("granted_by", sa.Uuid(), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        _check(
            "ck_admin_role_assignments__role_enum",
            "role",
            ["support", "moderator", "admin", "superadmin"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_admin_role_assignments__user_id__users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["users.id"],
            name="fk_admin_role_assignments__granted_by__users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("user_id", "role", name="pk_admin_role_assignments"),
    )

    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("handle", postgresql.CITEXT(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("avatar_media_id", sa.Uuid(), nullable=True),
        sa.Column("home_country_code", sa.Text(), nullable=True),
        sa.Column("home_region", sa.Text(), nullable=True),
        sa.Column(
            "travel_styles",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "interests", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column(
            "languages_spoken",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "account_visibility", sa.Text(), server_default=sa.text("'public'"), nullable=False
        ),
        sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        _check(
            "ck_user_profiles__account_visibility_enum",
            "account_visibility",
            ["public", "private"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_profiles__user_id__users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_profiles"),
        sa.UniqueConstraint("handle", name="uq_user_profiles__handle"),
    )
    op.create_index(
        "ix_user_profiles__travel_styles",
        "user_profiles",
        ["travel_styles"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_user_profiles__interests", "user_profiles", ["interests"], postgresql_using="gin"
    )

    op.create_table(
        "user_preferences",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("ui_locale", sa.Text(), nullable=False),
        sa.Column(
            "content_languages",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("time_zone", sa.Text(), server_default=sa.text("'UTC'"), nullable=False),
        sa.Column("currency_code", sa.Text(), server_default=sa.text("'USD'"), nullable=False),
        sa.Column("distance_unit", sa.Text(), server_default=sa.text("'km'"), nullable=False),
        sa.Column("auto_translate", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "notification_settings",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        _check("ck_user_preferences__distance_unit_enum", "distance_unit", ["km", "mi"]),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_preferences__user_id__users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_preferences"),
    )

    op.create_table(
        "user_privacy_settings",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "discovery_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "discovery_granularity", sa.Text(), server_default=sa.text("'city'"), nullable=False
        ),
        sa.Column(
            "connection_requests_from",
            sa.Text(),
            server_default=sa.text("'everyone'"),
            nullable=False,
        ),
        sa.Column(
            "profile_visibility", sa.Text(), server_default=sa.text("'public'"), nullable=False
        ),
        sa.Column(
            "show_trips_on_profile", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "read_receipts_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "post_location_default",
            sa.Text(),
            server_default=sa.text("'destination'"),
            nullable=False,
        ),
        sa.Column(
            "search_engine_indexing", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("location_consent_version", sa.Text(), nullable=True),
        sa.Column("location_consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discovery_consent_version", sa.Text(), nullable=True),
        sa.Column("discovery_consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        _check(
            "ck_user_privacy_settings__discovery_granularity_enum",
            "discovery_granularity",
            ["city", "neighborhood"],
        ),
        _check(
            "ck_user_privacy_settings__connection_requests_from_enum",
            "connection_requests_from",
            ["everyone", "shared_context", "nobody"],
        ),
        _check(
            "ck_user_privacy_settings__profile_visibility_enum",
            "profile_visibility",
            ["public", "connections"],
        ),
        _check(
            "ck_user_privacy_settings__post_location_default_enum",
            "post_location_default",
            ["none", "destination", "place"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_privacy_settings__user_id__users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_privacy_settings"),
    )

    # Idempotency keys belong to users (table from 0001; FK deferred until users existed).
    op.create_foreign_key(
        "fk_idempotency_keys__user_id__users",
        "idempotency_keys",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_idempotency_keys__user_id__users", "idempotency_keys", type_="foreignkey"
    )
    for table in (
        "user_privacy_settings",
        "user_preferences",
        "user_profiles",
        "admin_role_assignments",
        "consent_records",
        "retired_refresh_tokens",
        "user_sessions",
        "authentication_identities",
        "users",
    ):
        op.drop_table(table)
