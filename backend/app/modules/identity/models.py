"""Identity tables (docs/04 section 3). Private to the identity module."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, enum_check
from app.core.ids import uuid7


class UserStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"
    PENDING_DELETION = "pending_deletion"
    DELETED = "deleted"


class IdentityMethod(StrEnum):
    EMAIL_PASSWORD = "email_password"  # noqa: S105 - enum value, not a secret
    APPLE = "apple"
    GOOGLE = "google"
    OIDC = "oidc"
    DEV = "dev"


class SessionPlatform(StrEnum):
    IOS = "ios"
    ANDROID = "android"
    WEB = "web"


class RevokedReason(StrEnum):
    LOGOUT = "logout"
    USER_REVOKED = "user_revoked"
    REUSE_DETECTED = "reuse_detected"
    ADMIN = "admin"
    PASSWORD_CHANGED = "password_changed"  # noqa: S105 - enum value, not a secret
    ACCOUNT_DELETED = "account_deleted"


class ConsentType(StrEnum):
    TERMS = "terms"
    PRIVACY_POLICY = "privacy_policy"
    LOCATION = "location"
    TRAVELER_DISCOVERY = "traveler_discovery"
    MARKETING = "marketing"
    AI_PERSONALIZATION = "ai_personalization"
    POST_TRANSLATION = "post_translation"
    SEARCH_INDEXING = "search_indexing"


class ConsentSource(StrEnum):
    ONBOARDING = "onboarding"
    SETTINGS = "settings"
    PROMPT = "prompt"


class AdminRole(StrEnum):
    SUPPORT = "support"
    MODERATOR = "moderator"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        enum_check("status", UserStatus, "status_enum"),
        Index(
            "uq_users__email_active",
            "email",
            unique=True,
            postgresql_where=text("email IS NOT NULL AND status <> 'deleted'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"))
    email: Mapped[str | None] = mapped_column(CITEXT)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    birth_year: Mapped[int | None] = mapped_column(SmallInteger)
    age_assured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    primary_locale: Mapped[str] = mapped_column(Text)
    last_active_on: Mapped[date | None] = mapped_column(Date)
    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set by a temporary suspension; signing in after it lifts the suspension (ADM-002).
    suspended_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuthenticationIdentity(Base):
    __tablename__ = "authentication_identities"
    __table_args__ = (
        UniqueConstraint("issuer", "subject"),
        enum_check("method", IdentityMethod, "method_enum"),
        Index("ix_authentication_identities__user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    issuer: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(Text)
    email_at_link: Mapped[str | None] = mapped_column(CITEXT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    """A platform session == one refresh-token family (ADR-0003)."""

    __tablename__ = "user_sessions"
    __table_args__ = (
        UniqueConstraint("refresh_token_hash"),
        enum_check("platform", SessionPlatform, "platform_enum"),
        enum_check("revoked_reason", RevokedReason, "revoked_reason_enum"),
        Index(
            "ix_user_sessions__previous_refresh_token_hash",
            "previous_refresh_token_hash",
            postgresql_where=text("previous_refresh_token_hash IS NOT NULL"),
        ),
        Index(
            "ix_user_sessions__user_id_active",
            "user_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    refresh_token_hash: Mapped[bytes] = mapped_column(LargeBinary)
    previous_refresh_token_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_generation: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    device_id: Mapped[str | None] = mapped_column(Text)
    device_name: Mapped[str | None] = mapped_column(Text)
    platform: Mapped[str] = mapped_column(Text)
    app_version: Mapped[str | None] = mapped_column(Text)
    amr: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    auth_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(Text)
    # Collected only once the 30-day purge job exists (docs/04 section 14); unused until then.
    last_ip: Mapped[str | None] = mapped_column(INET)
    last_admin_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RetiredRefreshToken(Base):
    """Hashes of rotated refresh tokens, for reuse detection of any ancestor token."""

    __tablename__ = "retired_refresh_tokens"
    __table_args__ = (Index("ix_retired_refresh_tokens__session_id", "session_id"),)

    token_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_sessions.id", ondelete="CASCADE")
    )
    retired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ConsentRecord(Base):
    """Append-only consent history (GDPR accountability)."""

    __tablename__ = "consent_records"
    __table_args__ = (
        enum_check("consent_type", ConsentType, "consent_type_enum"),
        enum_check("source", ConsentSource, "source_enum"),
        Index(
            "ix_consent_records__user_type_recorded",
            "user_id",
            "consent_type",
            text("recorded_at DESC"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    consent_type: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(Text)
    granted: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AdminRoleAssignment(Base):
    __tablename__ = "admin_role_assignments"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "role"),
        enum_check("role", AdminRole, "role_enum"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(Text)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DataSubjectRequestKind(StrEnum):
    EXPORT = "export"
    DELETION = "deletion"
    RECTIFICATION = "rectification"


class DataSubjectRequestStatus(StrEnum):
    RECEIVED = "received"
    PROCESSING = "processing"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class DataSubjectRequest(Base):
    """GDPR requests: deletion and export. ``user_id`` has no foreign key on purpose: the record
    of a completed deletion outlives the account (accountability, docs/04 §12). An export keeps
    its archive's storage key until the 7-day link expires (BL-6.03)."""

    __tablename__ = "data_subject_requests"
    __table_args__ = (
        enum_check("kind", DataSubjectRequestKind, "kind_enum"),
        enum_check("status", DataSubjectRequestStatus, "status_enum"),
        Index("ix_data_subject_requests__user_id", "user_id", text("requested_at DESC")),
        Index(
            "uq_data_subject_requests__active_export",
            "user_id",
            unique=True,
            postgresql_where=text("kind = 'export' AND status IN ('received', 'processing')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    artifact_key: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PushProvider(StrEnum):
    EXPO = "expo"
    FCM = "fcm"
    APNS = "apns"
    WEBPUSH = "webpush"


class DevicePushToken(Base):
    """A push destination scoped to one session (NOTIF-002/005, docs/04 §3). Tokens and Web Push
    endpoints are capability secrets: stored encrypted, looked up by hash, never logged or
    returned. Revoking the session ends delivery."""

    __tablename__ = "device_push_tokens"
    __table_args__ = (
        enum_check("provider", PushProvider, "provider_enum"),
        UniqueConstraint("token_hash"),
        Index("ix_device_push_tokens__user_id", "user_id"),
        Index("ix_device_push_tokens__session_id", "session_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("user_sessions.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text)
    token_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary)
    webpush_p256dh: Mapped[bytes | None] = mapped_column(LargeBinary)
    webpush_auth: Mapped[bytes | None] = mapped_column(LargeBinary)
    device_id: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RealtimeTicket(Base):
    """Single-use browser WebSocket ticket (ADR-0013): only the SHA-256 of the 256-bit value is
    stored; 30 s to live; bound to the session that minted it (revoking it voids the ticket)."""

    __tablename__ = "realtime_tickets"
    __table_args__ = (Index("ix_realtime_tickets__expires_at", "expires_at"),)

    token_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("user_sessions.id", ondelete="CASCADE"), nullable=False
    )
    claims: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
