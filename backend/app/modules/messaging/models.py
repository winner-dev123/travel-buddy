"""Messaging tables (docs/04 §7). Private to the messaging module."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_check
from app.core.ids import uuid7
from app.modules.messaging.domain import (
    ConversationKind,
    MessageKind,
    ModerationState,
    NotificationLevel,
)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        enum_check("kind", ConversationKind, "kind_enum"),
        CheckConstraint(
            "(kind = 'direct' AND direct_key IS NOT NULL AND group_id IS NULL "
            "AND challenge_team_id IS NULL) "
            "OR (kind = 'group' AND group_id IS NOT NULL AND direct_key IS NULL "
            "AND challenge_team_id IS NULL) "
            "OR (kind = 'challenge_team' AND challenge_team_id IS NOT NULL "
            "AND direct_key IS NULL AND group_id IS NULL)",
            name="target_per_kind",
        ),
        CheckConstraint("last_seq >= 0", name="last_seq_nonnegative"),
        UniqueConstraint("direct_key"),
        Index(
            "uq_conversations__group_id",
            "group_id",
            unique=True,
            postgresql_where=text("kind = 'group'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    kind: Mapped[str] = mapped_column(Text)
    direct_key: Mapped[str | None] = mapped_column(Text)
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("travel_groups.id", ondelete="CASCADE")
    )
    # The foreign key to challenge_teams arrives with challenges.
    challenge_team_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    last_seq: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConversationMember(Base):
    __tablename__ = "conversation_members"
    __table_args__ = (
        PrimaryKeyConstraint("conversation_id", "user_id"),
        enum_check("notification_level", NotificationLevel, "notification_level_enum"),
        Index(
            "ix_conversation_members__active_user",
            "user_id",
            postgresql_where=text("left_at IS NULL"),
        ),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    joined_at_seq: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    muted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notification_level: Mapped[str] = mapped_column(Text, server_default=text("'all'"))
    cleared_through_seq: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq"),
        UniqueConstraint("conversation_id", "sender_id", "client_message_id"),
        enum_check("kind", MessageKind, "kind_enum"),
        enum_check("moderation_state", ModerationState, "moderation_state_enum"),
        CheckConstraint("seq >= 1", name="seq_positive"),
        CheckConstraint("char_length(body) <= 4000", name="body_length"),
        Index(
            "ix_messages__thread",
            "thread_root_id",
            "seq",
            postgresql_where=text("thread_root_id IS NOT NULL"),
        ),
        Index("ix_messages__sender_id", "sender_id"),
        # Bodies of deleted accounts awaiting erasure (retention job).
        Index(
            "ix_messages__orphaned",
            "id",
            postgresql_where=text(
                "sender_id IS NULL AND deleted_at IS NULL AND kind IN ('text', 'image')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(BigInteger)
    sender_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    client_message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(Text, server_default=text("'text'"))
    body: Mapped[str | None] = mapped_column(Text)
    reply_to_message_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("messages.id", ondelete="SET NULL")
    )
    thread_root_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("messages.id", ondelete="SET NULL")
    )
    moderation_state: Mapped[str] = mapped_column(Text, server_default=text("'visible'"))
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MessageAttachment(Base):
    """Private media only (purpose ``message``), served through signed URLs."""

    __tablename__ = "message_attachments"
    __table_args__ = (
        PrimaryKeyConstraint("message_id", "media_asset_id"),
        Index("ix_message_attachments__media_asset_id", "media_asset_id"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    media_asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))


class MessageReceipt(Base):
    """Per-member watermarks (not per-message rows); only ever move forward."""

    __tablename__ = "message_receipts"
    __table_args__ = (PrimaryKeyConstraint("conversation_id", "user_id"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    delivered_through_seq: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    read_through_seq: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MessageReaction(Base):
    __tablename__ = "message_reactions"
    __table_args__ = (
        PrimaryKeyConstraint("message_id", "user_id", "emoji"),
        CheckConstraint("octet_length(emoji) <= 16", name="emoji_length"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    emoji: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MessageMention(Base):
    __tablename__ = "message_mentions"
    __table_args__ = (
        PrimaryKeyConstraint("message_id", "user_id"),
        Index("ix_message_mentions__user", "user_id", text("message_id DESC")),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )


class ConversationPin(Base):
    __tablename__ = "conversation_pins"
    __table_args__ = (
        PrimaryKeyConstraint("conversation_id", "message_id"),
        Index("ix_conversation_pins__message_id", "message_id"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
    )
    pinned_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    pinned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
