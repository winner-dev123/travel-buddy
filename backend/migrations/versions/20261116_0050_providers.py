"""Guides and travel companies marketplace (ADR-0036, docs/18 §3).

* Eight ``provider*`` tables: business profiles that accounts belong to, service areas with a copy
  of each destination's ancestor path, private verification documents, offerings, requests,
  reviews and per-provider blocks.
* ``conversations`` gains kind ``provider``: one thread per provider and traveler.
* New enum values: media purposes ``provider`` and ``provider_document``, report targets
  ``provider``, ``provider_offering`` and ``provider_review``, five notification types and the
  ``provider_terms`` consent.

Revision ID: 0050
Revises: 0049
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0050"
down_revision: str | None = "0049"
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


def _texts(name: str) -> sa.Column[list[str]]:
    return sa.Column(
        name, postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
    )


def _zero(name: str, kind: type[sa.Integer] = sa.Integer) -> sa.Column[int]:
    return sa.Column(name, kind(), server_default=sa.text("0"), nullable=False)


def _replace(table: str, name: str, check: sa.CheckConstraint) -> None:
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
    op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({check.sqltext})")


def _restore(table: str, name: str, column: str, values: Sequence[str]) -> None:
    """Downgrade only: put back an enum constraint's previous values."""
    allowed = ", ".join(f"'{v}'" for v in values)
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
    op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({column} IN ({allowed}))")


_TARGET_PER_KIND = (
    "(kind = 'direct' AND direct_key IS NOT NULL AND group_id IS NULL "
    "AND challenge_team_id IS NULL) "
    "OR (kind = 'group' AND group_id IS NOT NULL AND direct_key IS NULL "
    "AND challenge_team_id IS NULL) "
    "OR (kind = 'challenge_team' AND challenge_team_id IS NOT NULL "
    "AND direct_key IS NULL AND group_id IS NULL)"
)
_PROVIDER_TARGET = (
    " OR (kind = 'provider' AND provider_id IS NOT NULL AND direct_key IS NULL "
    "AND group_id IS NULL AND challenge_team_id IS NULL)"
)

_OLD_NOTIFICATION_TYPES = (
    "connection_request",
    "connection_accepted",
    "new_message",
    "group_invitation",
    "group_announcement",
    "challenge_started",
    "challenge_result",
    "post_reaction",
    "post_comment",
    "new_follower",
    "follow_request",
    "moderation_notice",
    "subscription_notice",
    "ai_generation_ready",
    "data_export_ready",
)
_OLD_TARGETS = ("post", "comment", "user", "message", "group", "challenge", "media")
_OLD_CONSENTS = (
    "terms",
    "privacy_policy",
    "location",
    "traveler_discovery",
    "marketing",
    "ai_personalization",
    "post_translation",
    "search_indexing",
)


def upgrade() -> None:
    op.create_table(
        "providers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("legal_name", sa.Text(), nullable=True),
        sa.Column("tagline", sa.Text(), nullable=True),
        sa.Column("about", sa.Text(), nullable=True),
        sa.Column("country_code", sa.Text(), nullable=False),
        sa.Column("base_destination_id", sa.Uuid(), nullable=False),
        _texts("languages"),
        _texts("specialties"),
        sa.Column("years_experience", sa.SmallInteger(), nullable=True),
        sa.Column("website_url", sa.Text(), nullable=True),
        sa.Column("registration_number", sa.Text(), nullable=True),
        sa.Column("logo_media_id", sa.Uuid(), nullable=True),
        sa.Column("cover_media_id", sa.Uuid(), nullable=True),
        sa.Column("terms_version", sa.Text(), nullable=True),
        _ts("terms_accepted_at"),
        _ts("submitted_at"),
        _ts("decided_at"),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        _ts("approved_at"),
        sa.Column("suspended_reason", sa.Text(), nullable=True),
        _zero("rating_count"),
        _zero("rating_sum"),
        _zero("inquiry_count"),
        _zero("response_count"),
        _zero("response_seconds_total", sa.BigInteger),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        _ts("created_at", nullable=False, now=True),
        _ts("updated_at", nullable=False, now=True),
        _ts("deactivated_at"),
        _check("ck_providers__kind_enum", "kind", ["guide", "company"]),
        _check(
            "ck_providers__status_enum",
            "status",
            [
                "draft",
                "submitted",
                "changes_requested",
                "approved",
                "rejected",
                "suspended",
                "deactivated",
            ],
        ),
        _ck("ck_providers__display_name_length", "char_length(display_name) BETWEEN 2 AND 80"),
        _ck("ck_providers__tagline_length", "char_length(tagline) <= 120"),
        _ck("ck_providers__about_length", "char_length(about) <= 4000"),
        _ck("ck_providers__legal_name_length", "char_length(legal_name) <= 200"),
        _ck("ck_providers__registration_length", "char_length(registration_number) <= 64"),
        _ck("ck_providers__website_length", "char_length(website_url) <= 300"),
        _ck("ck_providers__country_code_format", "country_code ~ '^[A-Z]{2}$'"),
        _ck("ck_providers__years_range", "years_experience BETWEEN 0 AND 80"),
        _ck("ck_providers__languages_count", "cardinality(languages) <= 12"),
        _ck("ck_providers__specialties_count", "cardinality(specialties) <= 8"),
        _ck(
            "ck_providers__counters_nonnegative",
            "rating_count >= 0 AND rating_sum >= 0 AND inquiry_count >= 0 "
            "AND response_count >= 0 AND response_seconds_total >= 0",
        ),
        _fk("providers", "base_destination_id", "destinations", "RESTRICT"),
        _fk("providers", "logo_media_id", "media_assets", "SET NULL"),
        _fk("providers", "cover_media_id", "media_assets", "SET NULL"),
        _fk("providers", "decided_by", "users", "SET NULL"),
        _fk("providers", "created_by", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_providers"),
        sa.UniqueConstraint("slug", name="uq_providers__slug"),
    )
    op.create_index(
        "ix_providers__approved",
        "providers",
        ["approved_at"],
        postgresql_where=sa.text("status = 'approved'"),
    )
    op.create_index("ix_providers__queue", "providers", ["status", "submitted_at"])

    op.create_table(
        "provider_members",
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'invited'"), nullable=False),
        sa.Column("invited_by", sa.Uuid(), nullable=True),
        _ts("created_at", nullable=False, now=True),
        _ts("accepted_at"),
        _check("ck_provider_members__role_enum", "role", ["owner", "manager", "agent"]),
        _check("ck_provider_members__status_enum", "status", ["invited", "active"]),
        _fk("provider_members", "provider_id", "providers", "CASCADE"),
        _fk("provider_members", "user_id", "users", "CASCADE"),
        _fk("provider_members", "invited_by", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("provider_id", "user_id", name="pk_provider_members"),
    )
    op.create_index(
        "uq_provider_members__owner",
        "provider_members",
        ["provider_id"],
        unique=True,
        postgresql_where=sa.text("role = 'owner'"),
    )
    op.create_index("ix_provider_members__user", "provider_members", ["user_id", "status"])

    op.create_table(
        "provider_service_areas",
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("destination_id", sa.Uuid(), nullable=False),
        sa.Column("path", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("is_base", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        _fk("provider_service_areas", "provider_id", "providers", "CASCADE"),
        _fk("provider_service_areas", "destination_id", "destinations", "CASCADE"),
        sa.PrimaryKeyConstraint("provider_id", "destination_id", name="pk_provider_service_areas"),
    )
    op.create_index(
        "ix_provider_service_areas__path",
        "provider_service_areas",
        ["path"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_provider_service_areas__destination", "provider_service_areas", ["destination_id"]
    )

    op.create_table(
        "provider_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("media_id", sa.Uuid(), nullable=True),
        sa.Column("number", sa.Text(), nullable=True),
        sa.Column("issuing_country", sa.Text(), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        _ts("decided_at"),
        _ts("file_deleted_at"),
        _ts("created_at", nullable=False, now=True),
        _check(
            "ck_provider_documents__kind_enum",
            "kind",
            [
                "identity",
                "tourism_registry",
                "guide_license",
                "business_registration",
                "insurance",
                "other",
            ],
        ),
        _check("ck_provider_documents__status_enum", "status", ["pending", "accepted", "rejected"]),
        _ck("ck_provider_documents__number_length", "char_length(number) <= 64"),
        _ck(
            "ck_provider_documents__issuing_country_format",
            "issuing_country IS NULL OR issuing_country ~ '^[A-Z]{2}$'",
        ),
        _fk("provider_documents", "provider_id", "providers", "CASCADE"),
        _fk("provider_documents", "media_id", "media_assets", "SET NULL"),
        _fk("provider_documents", "uploaded_by", "users", "SET NULL"),
        _fk("provider_documents", "decided_by", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_provider_documents"),
    )
    op.create_index(
        "ix_provider_documents__provider", "provider_documents", ["provider_id", "created_at"]
    )

    op.create_table(
        "provider_offerings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("destination_id", sa.Uuid(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("price_from_minor", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column("price_unit", sa.Text(), nullable=True),
        sa.Column("max_group_size", sa.SmallInteger(), nullable=True),
        _texts("languages"),
        sa.Column("cover_media_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        _ts("published_at"),
        _ts("created_at", nullable=False, now=True),
        _ts("updated_at", nullable=False, now=True),
        _check(
            "ck_provider_offerings__status_enum",
            "status",
            ["draft", "published", "archived", "removed"],
        ),
        _check(
            "ck_provider_offerings__kind_enum",
            "kind",
            ["tour", "activity", "transfer", "package", "class", "other"],
        ),
        _check("ck_provider_offerings__price_unit_enum", "price_unit", ["per_person", "per_group"]),
        _ck("ck_provider_offerings__title_length", "char_length(title) BETWEEN 3 AND 100"),
        _ck("ck_provider_offerings__description_length", "char_length(description) <= 4000"),
        _ck("ck_provider_offerings__duration_range", "duration_minutes BETWEEN 15 AND 43200"),
        _ck("ck_provider_offerings__price_nonnegative", "price_from_minor >= 0"),
        _ck("ck_provider_offerings__currency_format", "currency ~ '^[A-Z]{3}$'"),
        _ck(
            "ck_provider_offerings__price_with_currency",
            "(price_from_minor IS NULL) = (currency IS NULL)",
        ),
        _ck("ck_provider_offerings__group_size_range", "max_group_size BETWEEN 1 AND 500"),
        _ck("ck_provider_offerings__languages_count", "cardinality(languages) <= 12"),
        _fk("provider_offerings", "provider_id", "providers", "CASCADE"),
        _fk("provider_offerings", "destination_id", "destinations", "RESTRICT"),
        _fk("provider_offerings", "cover_media_id", "media_assets", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_provider_offerings"),
    )
    op.create_index(
        "ix_provider_offerings__provider", "provider_offerings", ["provider_id", "status"]
    )
    op.create_index(
        "ix_provider_offerings__destination",
        "provider_offerings",
        ["destination_id"],
        postgresql_where=sa.text("status = 'published'"),
    )

    op.create_table(
        "provider_inquiries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("traveler_id", sa.Uuid(), nullable=True),
        sa.Column("offering_id", sa.Uuid(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("flexible_dates", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("party_size", sa.SmallInteger(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'open'"), nullable=False),
        sa.Column("decline_reason", sa.Text(), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        _ts("first_response_at"),
        _ts("decided_at"),
        _ts("completed_at"),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        _ts("created_at", nullable=False, now=True),
        _ts("updated_at", nullable=False, now=True),
        _check(
            "ck_provider_inquiries__status_enum",
            "status",
            ["open", "accepted", "declined", "withdrawn", "expired", "completed", "cancelled"],
        ),
        _ck("ck_provider_inquiries__party_size_range", "party_size BETWEEN 1 AND 50"),
        _ck("ck_provider_inquiries__message_length", "char_length(message) BETWEEN 10 AND 2000"),
        _ck("ck_provider_inquiries__decline_reason_length", "char_length(decline_reason) <= 500"),
        _ck(
            "ck_provider_inquiries__dates_order",
            "start_date IS NULL OR end_date IS NULL OR start_date <= end_date",
        ),
        _fk("provider_inquiries", "provider_id", "providers", "CASCADE"),
        _fk("provider_inquiries", "traveler_id", "users", "SET NULL"),
        _fk("provider_inquiries", "offering_id", "provider_offerings", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_provider_inquiries"),
    )
    op.create_index(
        "uq_provider_inquiries__open_pair",
        "provider_inquiries",
        ["provider_id", "traveler_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index(
        "ix_provider_inquiries__traveler", "provider_inquiries", ["traveler_id", "created_at"]
    )
    op.create_index(
        "ix_provider_inquiries__provider",
        "provider_inquiries",
        ["provider_id", "status", "created_at"],
    )
    op.create_index(
        "ix_provider_inquiries__conversation", "provider_inquiries", ["conversation_id"]
    )

    op.create_table(
        "provider_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("inquiry_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'visible'"), nullable=False),
        sa.Column("reply_body", sa.Text(), nullable=True),
        sa.Column("replied_by", sa.Uuid(), nullable=True),
        _ts("replied_at"),
        _ts("created_at", nullable=False, now=True),
        _ts("updated_at", nullable=False, now=True),
        _check("ck_provider_reviews__status_enum", "status", ["visible", "removed"]),
        _ck("ck_provider_reviews__rating_range", "rating BETWEEN 1 AND 5"),
        _ck("ck_provider_reviews__body_length", "char_length(body) <= 2000"),
        _ck("ck_provider_reviews__reply_length", "char_length(reply_body) <= 2000"),
        _fk("provider_reviews", "provider_id", "providers", "CASCADE"),
        _fk("provider_reviews", "inquiry_id", "provider_inquiries", "CASCADE"),
        _fk("provider_reviews", "author_id", "users", "SET NULL"),
        _fk("provider_reviews", "replied_by", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_provider_reviews"),
        sa.UniqueConstraint("inquiry_id", name="uq_provider_reviews__inquiry_id"),
    )
    op.create_index(
        "ix_provider_reviews__provider",
        "provider_reviews",
        ["provider_id", "status", "created_at"],
    )
    op.create_index("ix_provider_reviews__author", "provider_reviews", ["author_id"])

    op.create_table(
        "provider_blocks",
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("traveler_id", sa.Uuid(), nullable=False),
        sa.Column("side", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _ts("created_at", nullable=False, now=True),
        _check("ck_provider_blocks__side_enum", "side", ["traveler", "provider"]),
        _fk("provider_blocks", "provider_id", "providers", "CASCADE"),
        _fk("provider_blocks", "traveler_id", "users", "CASCADE"),
        _fk("provider_blocks", "created_by", "users", "SET NULL"),
        sa.PrimaryKeyConstraint("provider_id", "traveler_id", "side", name="pk_provider_blocks"),
    )
    op.create_index("ix_provider_blocks__traveler", "provider_blocks", ["traveler_id"])

    # Provider chats in messaging.
    op.add_column("conversations", sa.Column("provider_id", sa.Uuid(), nullable=True))
    op.add_column("conversations", sa.Column("provider_traveler_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_conversations__provider_id__providers",
        "conversations",
        "providers",
        ["provider_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_conversations__provider_traveler_id__users",
        "conversations",
        "users",
        ["provider_traveler_id"],
        ["id"],
        ondelete="SET NULL",
    )
    _replace(
        "conversations",
        "ck_conversations__kind_enum",
        _check(
            "ck_conversations__kind_enum",
            "kind",
            ["direct", "group", "challenge_team", "provider"],
        ),
    )
    _replace(
        "conversations",
        "ck_conversations__target_per_kind",
        _ck("ck_conversations__target_per_kind", _TARGET_PER_KIND + _PROVIDER_TARGET),
    )
    op.create_index(
        "uq_conversations__provider_pair",
        "conversations",
        ["provider_id", "provider_traveler_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'provider'"),
    )

    # Enum values used by the marketplace in other modules.
    _replace(
        "media_assets",
        "ck_media_assets__purpose_enum",
        _check(
            "ck_media_assets__purpose_enum",
            "purpose",
            [
                "post",
                "avatar",
                "message",
                "group_cover",
                "challenge",
                "editorial",
                "provider",
                "provider_document",
            ],
        ),
    )
    _replace(
        "content_reports",
        "ck_content_reports__target_type_enum",
        _check(
            "ck_content_reports__target_type_enum",
            "target_type",
            [
                "post",
                "comment",
                "user",
                "message",
                "group",
                "challenge",
                "media",
                "provider",
                "provider_offering",
                "provider_review",
            ],
        ),
    )
    _replace(
        "moderation_actions",
        "ck_moderation_actions__target_type_enum",
        _check(
            "ck_moderation_actions__target_type_enum",
            "target_type",
            [
                "post",
                "comment",
                "user",
                "message",
                "group",
                "challenge",
                "media",
                "provider",
                "provider_offering",
                "provider_review",
            ],
        ),
    )
    _replace(
        "notifications",
        "ck_notifications__type_enum",
        _check(
            "ck_notifications__type_enum",
            "type",
            [
                "connection_request",
                "connection_accepted",
                "new_message",
                "group_invitation",
                "group_announcement",
                "challenge_started",
                "challenge_result",
                "post_reaction",
                "post_comment",
                "new_follower",
                "follow_request",
                "moderation_notice",
                "subscription_notice",
                "ai_generation_ready",
                "data_export_ready",
                "provider_invitation",
                "provider_application",
                "provider_inquiry",
                "provider_inquiry_update",
                "provider_review",
            ],
        ),
    )
    _replace(
        "consent_records",
        "ck_consent_records__consent_type_enum",
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
                "provider_terms",
            ],
        ),
    )


def downgrade() -> None:
    op.execute("DELETE FROM consent_records WHERE consent_type = 'provider_terms'")
    _restore(
        "consent_records", "ck_consent_records__consent_type_enum", "consent_type", _OLD_CONSENTS
    )
    op.execute("DELETE FROM notifications WHERE type LIKE 'provider_%'")
    _restore("notifications", "ck_notifications__type_enum", "type", _OLD_NOTIFICATION_TYPES)
    op.execute("DELETE FROM moderation_actions WHERE target_type LIKE 'provider%'")
    op.execute("DELETE FROM content_reports WHERE target_type LIKE 'provider%'")
    for table in ("moderation_actions", "content_reports"):
        _restore(table, f"ck_{table}__target_type_enum", "target_type", _OLD_TARGETS)
    op.execute("DELETE FROM media_assets WHERE purpose IN ('provider', 'provider_document')")
    _restore(
        "media_assets",
        "ck_media_assets__purpose_enum",
        "purpose",
        ("post", "avatar", "message", "group_cover", "challenge", "editorial"),
    )

    op.execute("DELETE FROM conversations WHERE kind = 'provider'")
    op.drop_index("uq_conversations__provider_pair", table_name="conversations")
    op.execute("ALTER TABLE conversations DROP CONSTRAINT ck_conversations__target_per_kind")
    op.execute(
        "ALTER TABLE conversations ADD CONSTRAINT ck_conversations__target_per_kind "
        f"CHECK ({_TARGET_PER_KIND})"
    )
    _restore(
        "conversations",
        "ck_conversations__kind_enum",
        "kind",
        ("direct", "group", "challenge_team"),
    )
    op.drop_constraint(
        "fk_conversations__provider_traveler_id__users", "conversations", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_conversations__provider_id__providers", "conversations", type_="foreignkey"
    )
    op.drop_column("conversations", "provider_traveler_id")
    op.drop_column("conversations", "provider_id")

    for table in (
        "provider_blocks",
        "provider_reviews",
        "provider_inquiries",
        "provider_offerings",
        "provider_documents",
        "provider_service_areas",
        "provider_members",
        "providers",
    ):
        op.drop_table(table)
