"""Provider tables (docs/18 §3, migration 0050). Private to the providers module."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_check
from app.core.ids import uuid7
from app.modules.providers.domain import (
    DocumentKind,
    DocumentStatus,
    InquiryStatus,
    MemberRole,
    MemberStatus,
    OfferingKind,
    OfferingStatus,
    PriceUnit,
    ProviderKind,
    ProviderStatus,
    ReviewStatus,
    Side,
)


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Provider(Base):
    __tablename__ = "providers"
    __table_args__ = (
        enum_check("kind", ProviderKind, "kind_enum"),
        enum_check("status", ProviderStatus, "status_enum"),
        CheckConstraint("char_length(display_name) BETWEEN 2 AND 80", name="display_name_length"),
        CheckConstraint("char_length(tagline) <= 120", name="tagline_length"),
        CheckConstraint("char_length(about) <= 4000", name="about_length"),
        CheckConstraint("char_length(legal_name) <= 200", name="legal_name_length"),
        CheckConstraint("char_length(registration_number) <= 64", name="registration_length"),
        CheckConstraint("char_length(website_url) <= 300", name="website_length"),
        CheckConstraint("country_code ~ '^[A-Z]{2}$'", name="country_code_format"),
        CheckConstraint("years_experience BETWEEN 0 AND 80", name="years_range"),
        CheckConstraint("cardinality(languages) <= 12", name="languages_count"),
        CheckConstraint("cardinality(specialties) <= 8", name="specialties_count"),
        CheckConstraint(
            "rating_count >= 0 AND rating_sum >= 0 AND inquiry_count >= 0 "
            "AND response_count >= 0 AND response_seconds_total >= 0",
            name="counters_nonnegative",
        ),
        UniqueConstraint("slug"),
        Index(
            "ix_providers__approved",
            "approved_at",
            postgresql_where=text("status = 'approved'"),
        ),
        Index("ix_providers__queue", "status", "submitted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'draft'"))
    slug: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    legal_name: Mapped[str | None] = mapped_column(Text)
    tagline: Mapped[str | None] = mapped_column(Text)
    about: Mapped[str | None] = mapped_column(Text)
    country_code: Mapped[str] = mapped_column(Text)
    base_destination_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("destinations.id", ondelete="RESTRICT")
    )
    languages: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    specialties: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    years_experience: Mapped[int | None] = mapped_column(SmallInteger)
    website_url: Mapped[str | None] = mapped_column(Text)
    registration_number: Mapped[str | None] = mapped_column(Text)
    logo_media_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="SET NULL")
    )
    cover_media_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="SET NULL")
    )
    terms_version: Mapped[str | None] = mapped_column(Text)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    review_note: Mapped[str | None] = mapped_column(Text)
    # First approval: locks the checked fields (PROV-003) and orders new providers.
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspended_reason: Mapped[str | None] = mapped_column(Text)
    rating_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    rating_sum: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    inquiry_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    response_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    response_seconds_total: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderMember(Base):
    __tablename__ = "provider_members"
    __table_args__ = (
        PrimaryKeyConstraint("provider_id", "user_id"),
        enum_check("role", MemberRole, "role_enum"),
        enum_check("status", MemberStatus, "status_enum"),
        Index(
            "uq_provider_members__owner",
            "provider_id",
            unique=True,
            postgresql_where=text("role = 'owner'"),
        ),
        Index("ix_provider_members__user", "user_id", "status"),
    )

    provider_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("providers.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'invited'"))
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _now()
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ProviderServiceArea(Base):
    """Base town and service areas, each with a copy of the destination's ancestor path so a
    listing can match "this place or anything inside it" without reading destination tables."""

    __tablename__ = "provider_service_areas"
    __table_args__ = (
        PrimaryKeyConstraint("provider_id", "destination_id"),
        Index("ix_provider_service_areas__path", "path", postgresql_using="gin"),
        Index("ix_provider_service_areas__destination", "destination_id"),
    )

    provider_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("providers.id", ondelete="CASCADE")
    )
    destination_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("destinations.id", ondelete="CASCADE")
    )
    path: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid))
    is_base: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class ProviderDocument(Base):
    __tablename__ = "provider_documents"
    __table_args__ = (
        enum_check("kind", DocumentKind, "kind_enum"),
        enum_check("status", DocumentStatus, "status_enum"),
        CheckConstraint("char_length(number) <= 64", name="number_length"),
        CheckConstraint(
            "issuing_country IS NULL OR issuing_country ~ '^[A-Z]{2}$'",
            name="issuing_country_format",
        ),
        Index("ix_provider_documents__provider", "provider_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("providers.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(Text)
    media_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="SET NULL")
    )
    number: Mapped[str | None] = mapped_column(Text)
    issuing_country: Mapped[str | None] = mapped_column(Text)
    expires_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    file_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()


class ProviderOffering(Base):
    __tablename__ = "provider_offerings"
    __table_args__ = (
        enum_check("status", OfferingStatus, "status_enum"),
        enum_check("kind", OfferingKind, "kind_enum"),
        enum_check("price_unit", PriceUnit, "price_unit_enum"),
        CheckConstraint("char_length(title) BETWEEN 3 AND 100", name="title_length"),
        CheckConstraint("char_length(description) <= 4000", name="description_length"),
        CheckConstraint("duration_minutes BETWEEN 15 AND 43200", name="duration_range"),
        CheckConstraint("price_from_minor >= 0", name="price_nonnegative"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint(
            "(price_from_minor IS NULL) = (currency IS NULL)", name="price_with_currency"
        ),
        CheckConstraint("max_group_size BETWEEN 1 AND 500", name="group_size_range"),
        CheckConstraint("cardinality(languages) <= 12", name="languages_count"),
        Index("ix_provider_offerings__provider", "provider_id", "status"),
        Index(
            "ix_provider_offerings__destination",
            "destination_id",
            postgresql_where=text("status = 'published'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("providers.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'draft'"))
    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    destination_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("destinations.id", ondelete="RESTRICT")
    )
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    price_from_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(Text)
    price_unit: Mapped[str | None] = mapped_column(Text)
    max_group_size: Mapped[int | None] = mapped_column(SmallInteger)
    languages: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    cover_media_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="SET NULL")
    )
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProviderInquiry(Base):
    __tablename__ = "provider_inquiries"
    __table_args__ = (
        enum_check("status", InquiryStatus, "status_enum"),
        CheckConstraint("party_size BETWEEN 1 AND 50", name="party_size_range"),
        CheckConstraint("char_length(message) BETWEEN 10 AND 2000", name="message_length"),
        CheckConstraint("char_length(decline_reason) <= 500", name="decline_reason_length"),
        CheckConstraint(
            "start_date IS NULL OR end_date IS NULL OR start_date <= end_date", name="dates_order"
        ),
        Index(
            "uq_provider_inquiries__open_pair",
            "provider_id",
            "traveler_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_provider_inquiries__traveler", "traveler_id", "created_at"),
        Index("ix_provider_inquiries__provider", "provider_id", "status", "created_at"),
        Index("ix_provider_inquiries__conversation", "conversation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("providers.id", ondelete="CASCADE")
    )
    traveler_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    offering_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("provider_offerings.id", ondelete="SET NULL")
    )
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    flexible_dates: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    party_size: Mapped[int] = mapped_column(SmallInteger)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'open'"))
    decline_reason: Mapped[str | None] = mapped_column(Text)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # messaging owns the room
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProviderReview(Base):
    __tablename__ = "provider_reviews"
    __table_args__ = (
        enum_check("status", ReviewStatus, "status_enum"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),
        CheckConstraint("char_length(body) <= 2000", name="body_length"),
        CheckConstraint("char_length(reply_body) <= 2000", name="reply_length"),
        UniqueConstraint("inquiry_id"),
        Index("ix_provider_reviews__provider", "provider_id", "status", "created_at"),
        Index("ix_provider_reviews__author", "author_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("providers.id", ondelete="CASCADE")
    )
    inquiry_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("provider_inquiries.id", ondelete="CASCADE")
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    rating: Mapped[int] = mapped_column(SmallInteger)
    body: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'visible'"))
    reply_body: Mapped[str | None] = mapped_column(Text)
    replied_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ProviderBlock(Base):
    __tablename__ = "provider_blocks"
    __table_args__ = (
        PrimaryKeyConstraint("provider_id", "traveler_id", "side"),
        enum_check("side", Side, "side_enum"),
        Index("ix_provider_blocks__traveler", "traveler_id"),
    )

    provider_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("providers.id", ondelete="CASCADE")
    )
    traveler_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    side: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _now()
