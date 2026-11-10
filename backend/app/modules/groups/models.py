"""Group tables (docs/04 §8). Private to the groups module. System roles are a fixed matrix in
``domain.py`` (custom roles, and the ``group_roles`` table for them, come later)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_check
from app.core.ids import uuid7
from app.modules.groups.domain import (
    GroupStatus,
    InvitationKind,
    InvitationStatus,
    MembershipStatus,
    Role,
    TransferStatus,
)


class TravelGroup(Base):
    __tablename__ = "travel_groups"
    __table_args__ = (
        enum_check("visibility", ("private", "unlisted", "public"), "visibility_enum"),
        enum_check("join_policy", ("invite_only", "request_to_join"), "join_policy_enum"),
        enum_check("status", GroupStatus, "status_enum"),
        CheckConstraint("char_length(name) BETWEEN 3 AND 60", name="name_length"),
        CheckConstraint("member_capacity BETWEEN 2 AND 50", name="capacity_range"),
        CheckConstraint(
            "start_date IS NULL OR end_date IS NULL OR start_date <= end_date", name="dates_order"
        ),
        Index(
            "ix_travel_groups__owner_active", "owner_id", postgresql_where=text("status = 'active'")
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    cover_media_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="SET NULL")
    )
    primary_destination_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("destinations.id", ondelete="RESTRICT"), nullable=False
    )
    trip_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # FK arrives with trips
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    visibility: Mapped[str] = mapped_column(Text, server_default=text("'private'"))
    join_policy: Mapped[str] = mapped_column(Text, server_default=text("'invite_only'"))
    member_capacity: Mapped[int] = mapped_column(Integer, server_default=text("20"))
    interests: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    # Handed over before the owner's account is erased; NULL only for groups nobody was left in.
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Last owner-lapse notice sent (None, grace, grace_ending, lapsed); docs/07 §5.
    premium_notice: Mapped[str | None] = mapped_column(Text)


class GroupSettings(Base):
    __tablename__ = "group_settings"
    __table_args__ = (
        enum_check("chat_mode", ("everyone", "admins_only"), "chat_mode_enum"),
        enum_check("new_member_history", ("full", "from_join"), "history_enum"),
    )

    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("travel_groups.id", ondelete="CASCADE"), primary_key=True
    )
    members_can_invite: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    chat_mode: Mapped[str] = mapped_column(Text, server_default=text("'everyone'"))
    new_member_history: Mapped[str] = mapped_column(Text, server_default=text("'full'"))
    challenge_defaults: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class GroupMembership(Base):
    __tablename__ = "group_memberships"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id"),
        enum_check("role", Role, "role_enum"),
        enum_check("status", MembershipStatus, "status_enum"),
        Index("ix_group_memberships__user_status", "user_id", "status"),
        # Exactly one active owner per group.
        Index(
            "uq_group_memberships__owner",
            "group_id",
            unique=True,
            postgresql_where=text("role = 'owner' AND status IN ('active', 'restricted')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("travel_groups.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(Text, server_default=text("'member'"))
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"))
    restricted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    removed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removal_reason: Mapped[str | None] = mapped_column(Text)


class GroupInvitation(Base):
    __tablename__ = "group_invitations"
    __table_args__ = (
        enum_check("kind", InvitationKind, "kind_enum"),
        enum_check("status", InvitationStatus, "status_enum"),
        UniqueConstraint("token_hash"),
        CheckConstraint("use_count <= max_uses", name="uses_within_max"),
        CheckConstraint("max_uses BETWEEN 1 AND 100", name="max_uses_range"),
        Index(
            "uq_group_invitations__active_direct",
            "group_id",
            "invitee_user_id",
            unique=True,
            postgresql_where=text("kind = 'direct' AND status = 'active'"),
        ),
        Index("ix_group_invitations__invitee", "invitee_user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("travel_groups.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text)
    invitee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE")
    )
    token_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    max_uses: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    use_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GroupOwnershipTransfer(Base):
    __tablename__ = "group_ownership_transfers"
    __table_args__ = (
        enum_check("status", TransferStatus, "status_enum"),
        Index(
            "uq_group_ownership_transfers__pending",
            "group_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("travel_groups.id", ondelete="CASCADE"), nullable=False
    )
    from_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    to_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
