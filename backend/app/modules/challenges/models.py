"""Challenge tables (docs/04 §9). Private to the challenges module.

Accepted answers live in their own table and are never serialized to members (CHAL-008).
Submissions are append-only (CHAL-009).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    PrimaryKeyConstraint,
    SmallInteger,
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

STATUSES = ("draft", "scheduled", "active", "judging", "completed", "cancelled")
SOLVING_MODES = ("individual", "team")
VALIDATION_METHODS = ("exact", "admin_review", "ai_assisted")
WINNER_POLICIES = ("first_correct", "first_n_correct", "all_correct", "admin_selects")
REWARD_TYPES = ("badge", "achievement", "discount_code", "promotional")
FULFILLMENT_OWNERS = ("platform", "group_admin", "sponsor")
REVIEW_STATUSES = ("not_required", "pending", "approved", "rejected")
EVALUATIONS = ("pending", "correct", "incorrect", "needs_review", "void")
EVALUATORS = ("exact", "ai", "admin")
PARTICIPANT_STATUSES = ("active", "disqualified", "withdrawn")
WINNER_STATUSES = ("provisional", "confirmed", "revoked")
FULFILLMENT_STATUSES = ("pending", "issued", "delivered", "failed", "cancelled", "disputed")
DISPUTE_STATUSES = ("open", "upheld", "rejected")


class GroupChallenge(Base):
    __tablename__ = "group_challenges"
    __table_args__ = (
        enum_check("kind", ("riddle",), "kind_enum"),
        enum_check("status", STATUSES, "status_enum"),
        enum_check("solving_mode", SOLVING_MODES, "solving_mode_enum"),
        enum_check("validation_method", VALIDATION_METHODS, "validation_method_enum"),
        enum_check("winner_policy", WINNER_POLICIES, "winner_policy_enum"),
        CheckConstraint("starts_at < ends_at", name="window"),
        CheckConstraint("max_attempts BETWEEN 1 AND 20", name="max_attempts_range"),
        CheckConstraint("max_winners BETWEEN 1 AND 50", name="max_winners_range"),
        Index("ix_group_challenges__group_status", "group_id", "status", "starts_at"),
        Index(
            "ix_group_challenges__scheduled",
            "status",
            "starts_at",
            postgresql_where=text("status = 'scheduled'"),
        ),
        Index(
            "ix_group_challenges__active",
            "status",
            "ends_at",
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("travel_groups.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(Text, server_default=text("'riddle'"))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    media_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="SET NULL")
    )
    solving_mode: Mapped[str] = mapped_column(Text)
    validation_method: Mapped[str] = mapped_column(Text)
    normalization: Mapped[dict[str, Any]] = mapped_column(JSONB)
    max_attempts: Mapped[int] = mapped_column(SmallInteger)
    attempt_cooldown_seconds: Mapped[int] = mapped_column(Integer, server_default=text("30"))
    winner_policy: Mapped[str] = mapped_column(Text)
    max_winners: Mapped[int] = mapped_column(SmallInteger, server_default=text("1"))
    prize_description: Mapped[str | None] = mapped_column(Text)
    participation_rules: Mapped[str | None] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, server_default=text("'draft'"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    results_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    rules_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChallengeAnswer(Base):
    """Never serialized to members; judges read it through an audited endpoint (CHAL-008)."""

    __tablename__ = "challenge_answers"
    __table_args__ = (UniqueConstraint("challenge_id", "answer_normalized"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    challenge_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("group_challenges.id", ondelete="CASCADE"), nullable=False
    )
    answer_display: Mapped[str] = mapped_column(Text)
    answer_normalized: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChallengeHint(Base):
    __tablename__ = "challenge_hints"
    __table_args__ = (
        UniqueConstraint("challenge_id", "sort_order"),
        CheckConstraint("char_length(body) BETWEEN 1 AND 500", name="body_length"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    challenge_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("group_challenges.id", ondelete="CASCADE"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(SmallInteger)
    body: Mapped[str] = mapped_column(Text)
    release_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Badge(Base):
    __tablename__ = "badges"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    key: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text)
    icon_media_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("media_assets.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserBadge(Base):
    """Non-transferable by design: there is no endpoint or column that moves a badge."""

    __tablename__ = "user_badges"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "badge_id", "source_id"),
        enum_check("source_type", ("challenge", "platform"), "source_type_enum"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    badge_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("badges.id", ondelete="CASCADE"), nullable=False
    )
    source_type: Mapped[str] = mapped_column(Text)
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    awarded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChallengeReward(Base):
    __tablename__ = "challenge_rewards"
    __table_args__ = (
        enum_check("reward_type", REWARD_TYPES, "reward_type_enum"),
        enum_check("fulfillment_owner", FULFILLMENT_OWNERS, "fulfillment_owner_enum"),
        enum_check("review_status", REVIEW_STATUSES, "review_status_enum"),
        CheckConstraint("quantity BETWEEN 1 AND 100", name="quantity_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    challenge_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("group_challenges.id", ondelete="CASCADE"), nullable=False
    )
    reward_type: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    badge_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("badges.id", ondelete="SET NULL")
    )
    sponsor_name: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[int] = mapped_column(SmallInteger)
    eligibility_rules: Mapped[str | None] = mapped_column(Text)
    terms_url: Mapped[str | None] = mapped_column(Text)
    fulfillment_owner: Mapped[str] = mapped_column(Text)
    requires_platform_review: Mapped[bool] = mapped_column(server_default=text("false"))
    review_status: Mapped[str] = mapped_column(Text, server_default=text("'not_required'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChallengeTeam(Base):
    """Team mode (CHAL-004): only the captain submits; attempts count per team."""

    __tablename__ = "challenge_teams"
    __table_args__ = (
        UniqueConstraint("challenge_id", "name"),
        CheckConstraint("char_length(name) BETWEEN 2 AND 40", name="name_length"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    challenge_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("group_challenges.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text)
    captain_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="SET NULL")
    )
    attempts_used: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChallengeParticipant(Base):
    __tablename__ = "challenge_participants"
    __table_args__ = (
        PrimaryKeyConstraint("challenge_id", "user_id"),
        enum_check("status", PARTICIPANT_STATUSES, "status_enum"),
        Index("ix_challenge_participants__team_id", "team_id"),
    )

    challenge_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("group_challenges.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("challenge_teams.id", ondelete="SET NULL")
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attempts_used: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, server_default=text("'active'"))


class ChallengeSubmission(Base):
    """Append-only and auditable (CHAL-009)."""

    __tablename__ = "challenge_submissions"
    __table_args__ = (
        # Explicit name: the generated one would pass the 63-character identifier limit.
        UniqueConstraint(
            "challenge_id",
            "submitted_by",
            "idempotency_key",
            name="uq_challenge_submissions__idempotency",
        ),
        enum_check("evaluation_status", EVALUATIONS, "evaluation_status_enum"),
        enum_check("evaluator", EVALUATORS, "evaluator_enum"),
        Index("ix_challenge_submissions__challenge_time", "challenge_id", "submitted_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    challenge_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("group_challenges.id", ondelete="CASCADE"), nullable=False
    )
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("challenge_teams.id", ondelete="SET NULL")
    )
    attempt_no: Mapped[int] = mapped_column(SmallInteger)
    answer_text: Mapped[str] = mapped_column(Text)
    answer_normalized: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(Uuid)
    evaluation_status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    evaluator: Mapped[str | None] = mapped_column(Text)
    evaluated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    ai_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    ai_rationale: Mapped[str | None] = mapped_column(Text)
    rules_version: Mapped[int] = mapped_column(Integer)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChallengeWinner(Base):
    __tablename__ = "challenge_winners"
    __table_args__ = (
        enum_check("status", WINNER_STATUSES, "status_enum"),
        enum_check("determined_by", ("system", "admin"), "determined_by_enum"),
        CheckConstraint("(user_id IS NULL) <> (team_id IS NULL)", name="one_recipient"),
        Index(
            "uq_challenge_winners__rank",
            "challenge_id",
            "rank",
            unique=True,
            postgresql_where=text("status <> 'revoked'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    challenge_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("group_challenges.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("challenge_teams.id", ondelete="CASCADE")
    )
    submission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("challenge_submissions.id", ondelete="CASCADE"), nullable=False
    )
    rank: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(Text, server_default=text("'provisional'"))
    determined_by: Mapped[str] = mapped_column(Text, server_default=text("'system'"))
    determined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )


class RewardFulfillment(Base):
    """A real-world reward on its way to a winner (CHAL-015). The secret (a discount code) is
    encrypted at rest and shown only to the recipient; every transition is audited."""

    __tablename__ = "reward_fulfillments"
    __table_args__ = (
        UniqueConstraint("challenge_reward_id", "winner_id"),
        enum_check("status", FULFILLMENT_STATUSES, "status_enum"),
        Index("ix_reward_fulfillments__recipient", "recipient_user_id", "created_at"),
        Index("ix_reward_fulfillments__challenge", "challenge_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    challenge_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("group_challenges.id", ondelete="CASCADE"), nullable=False
    )
    challenge_reward_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("challenge_rewards.id", ondelete="CASCADE"), nullable=False
    )
    winner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("challenge_winners.id", ondelete="CASCADE"), nullable=False
    )
    recipient_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    secret_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    issued_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChallengeDispute(Base):
    """Raised by participants, resolved by judges (audited), escalated via reports (CHAL-016)."""

    __tablename__ = "challenge_disputes"
    __table_args__ = (
        enum_check("status", DISPUTE_STATUSES, "status_enum"),
        CheckConstraint("char_length(reason) BETWEEN 10 AND 1000", name="reason_length"),
        Index("ix_challenge_disputes__challenge", "challenge_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    challenge_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("group_challenges.id", ondelete="CASCADE"), nullable=False
    )
    raised_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    submission_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("challenge_submissions.id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=text("'open'"))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    resolution_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
