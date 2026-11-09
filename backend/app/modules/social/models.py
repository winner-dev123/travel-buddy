"""Social tables (docs/04 section 5). Private to the social module."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_check
from app.core.ids import uuid7


class PostKind(StrEnum):
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    STORY = "story"
    ATTRACTION_RECOMMENDATION = "attraction_recommendation"
    RESTAURANT_RECOMMENDATION = "restaurant_recommendation"
    REVIEW = "review"
    TIP = "tip"
    ITINERARY_SUMMARY = "itinerary_summary"
    EXPERIENCE = "experience"


class PostVisibility(StrEnum):
    PUBLIC = "public"
    FOLLOWERS = "followers"
    CONNECTIONS = "connections"
    PRIVATE = "private"


class LocationPrecision(StrEnum):
    NONE = "none"
    DESTINATION = "destination"
    PLACE = "place"


class PostStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    DELETED = "deleted"


class ModerationState(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    LIMITED = "limited"
    REMOVED = "removed"


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        enum_check("kind", PostKind, "kind_enum"),
        enum_check("visibility", PostVisibility, "visibility_enum"),
        enum_check("location_precision", LocationPrecision, "location_precision_enum"),
        enum_check("status", PostStatus, "status_enum"),
        enum_check("moderation_state", ModerationState, "moderation_state_enum"),
        CheckConstraint(
            "rating IS NULL OR (kind = 'review' AND rating BETWEEN 1 AND 5)",
            name="rating_only_reviews",
        ),
        CheckConstraint(
            "(location_precision = 'none') = (primary_destination_id IS NULL)",
            name="destination_required_unless_none",
        ),
        CheckConstraint("char_length(body) <= 5000", name="body_length"),
        Index(
            "ix_posts__author_published",
            "author_id",
            text("published_at DESC"),
            postgresql_where=text("status = 'published'"),
        ),
        Index(
            "ix_posts__public_published",
            text("published_at DESC"),
            postgresql_where=text(
                "status = 'published' AND visibility = 'public' "
                "AND moderation_state IN ('approved', 'pending')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(Text)
    # FK to places is added with the places module (Phase 4, DEST-003).
    place_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    location_precision: Mapped[str] = mapped_column(Text)
    primary_destination_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("destinations.id", ondelete="RESTRICT")
    )
    travel_date: Mapped[date | None] = mapped_column(Date)
    rating: Mapped[int | None] = mapped_column(SmallInteger)
    # FK to trips is added with the trips module.
    trip_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(Text, server_default=text("'published'"))
    moderation_state: Mapped[str] = mapped_column(Text, server_default=text("'approved'"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reaction_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    comment_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    bookmark_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    share_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    quality_score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PostDestination(Base):
    """Ancestor fan-out: one row per destination a post belongs to (feed index)."""

    __tablename__ = "post_destinations"
    __table_args__ = (
        Index(
            "ix_post_destinations__feed",
            "destination_id",
            text("published_at DESC"),
            postgresql_where=text("visibility_public"),
        ),
    )

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
    destination_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("destinations.id", ondelete="RESTRICT"), primary_key=True
    )
    is_primary: Mapped[bool] = mapped_column(Boolean)
    depth_from_primary: Mapped[int] = mapped_column(SmallInteger)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Public post, by a public account, not removed by moderation (feeds for everyone).
    visibility_public: Mapped[bool] = mapped_column(Boolean)


class PostTag(Base):
    __tablename__ = "post_tags"
    __table_args__ = (Index("ix_post_tags__tag", "tag"),)

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
    tag: Mapped[str] = mapped_column(CITEXT, primary_key=True)
