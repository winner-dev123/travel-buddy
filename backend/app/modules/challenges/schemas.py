"""Challenge API shapes (contract ``CreateChallengeRequest``, ``Challenge``,
``ChallengeManagerView`` …). Member views never carry answers or unreleased hints (CHAL-008)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.pagination import PageInfo
from app.modules.media.schemas import MediaRef
from app.modules.profiles.schemas import UserSummary

SolvingMode = Literal["individual", "team"]
ValidationMethod = Literal["exact", "admin_review", "ai_assisted"]
WinnerPolicy = Literal["first_correct", "first_n_correct", "all_correct", "admin_selects"]
ChallengeStatus = Literal["draft", "scheduled", "active", "judging", "completed", "cancelled"]
RewardType = Literal["badge", "achievement", "discount_code", "promotional"]
FulfillmentOwner = Literal["platform", "group_admin", "sponsor"]
EvaluationStatus = Literal["pending", "correct", "incorrect", "needs_review", "void"]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True)


class AnswerNormalization(_Request):
    case_fold: bool = True
    strip_accents: bool = True
    strip_punctuation: bool = True
    collapse_whitespace: bool = True
    strip_articles: list[str] = Field(default_factory=list, max_length=10)


class HintInput(_Request):
    body: str = Field(min_length=1, max_length=500)
    release_at: datetime | None = None


class CreateRewardRequest(_Request):
    reward_type: RewardType
    title: str = Field(min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    badge_key: str | None = Field(default=None, max_length=60)
    sponsor_name: str | None = Field(default=None, max_length=100)
    quantity: int = Field(ge=1, le=100)
    eligibility_rules: str | None = Field(default=None, max_length=2000)
    terms_url: str | None = Field(default=None, max_length=500)
    fulfillment_owner: FulfillmentOwner


class CreateChallengeRequest(_Request):
    kind: Literal["riddle"]
    title: str = Field(min_length=3, max_length=100)
    description: str = Field(min_length=10, max_length=4000)
    media_id: uuid.UUID | None = None
    solving_mode: SolvingMode
    validation_method: ValidationMethod
    accepted_answers: list[str] | None = Field(default=None, min_length=1, max_length=20)
    normalization: AnswerNormalization = Field(default_factory=AnswerNormalization)
    hints: list[HintInput] = Field(default_factory=list, max_length=10)
    starts_at: datetime
    ends_at: datetime
    max_attempts: int = Field(ge=1, le=20)
    attempt_cooldown_seconds: int = Field(default=30, ge=0, le=3600)
    winner_policy: WinnerPolicy
    max_winners: int = Field(default=1, ge=1, le=50)
    prize_description: str | None = Field(default=None, max_length=500)
    rewards: list[CreateRewardRequest] = Field(default_factory=list, max_length=5)
    participation_rules: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _rules(self) -> Self:
        if self.starts_at >= self.ends_at:
            raise ValueError("starts_at must be before ends_at")
        if self.validation_method != "admin_review" and not self.accepted_answers:
            raise ValueError("accepted_answers are required unless answers are reviewed by admins")
        if any(not answer.strip() or len(answer) > 200 for answer in self.accepted_answers or []):
            raise ValueError("accepted answers are 1-200 characters")
        return self


class UpdateChallengeRequest(_Request):
    title: str | None = Field(default=None, min_length=3, max_length=100)
    description: str | None = Field(default=None, min_length=10, max_length=4000)
    media_id: uuid.UUID | None = None
    accepted_answers: list[str] | None = Field(default=None, min_length=1, max_length=20)
    normalization: AnswerNormalization | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    max_attempts: int | None = Field(default=None, ge=1, le=20)
    attempt_cooldown_seconds: int | None = Field(default=None, ge=0, le=3600)
    winner_policy: WinnerPolicy | None = None
    max_winners: int | None = Field(default=None, ge=1, le=50)
    prize_description: str | None = Field(default=None, max_length=500)
    participation_rules: str | None = Field(default=None, max_length=2000)


class CancelRequest(_Request):
    reason: str = Field(min_length=3, max_length=500)


class ChallengeHintOut(_Out):
    id: uuid.UUID
    sort_order: int
    body: str
    released_at: datetime


class ManagedHint(_Out):
    id: uuid.UUID
    sort_order: int
    body: str
    release_at: datetime | None


class HintList(_Out):
    data: list[ChallengeHintOut]


class BadgeSummary(_Out):
    id: uuid.UUID
    key: str
    name: str
    icon: MediaRef | None = None


class RewardSummary(_Out):
    id: uuid.UUID
    reward_type: RewardType
    title: str
    description: str | None
    sponsor_name: str | None
    quantity: int
    terms_url: str | None


class RewardDetail(_Out):
    id: uuid.UUID
    challenge_id: uuid.UUID
    reward_type: RewardType
    title: str
    description: str | None
    badge: BadgeSummary | None
    sponsor_name: str | None
    quantity: int
    eligibility_rules: str | None
    terms_url: str | None
    fulfillment_owner: FulfillmentOwner
    requires_platform_review: bool
    review_status: Literal["not_required", "pending", "approved", "rejected"]
    created_at: datetime


class Participation(_Out):
    attempts_used: int
    attempts_remaining: int
    next_attempt_at: datetime | None
    team_id: uuid.UUID | None
    is_captain: bool
    status: Literal["active", "disqualified", "withdrawn"]


class ChallengeOut(_Out):
    id: uuid.UUID
    group_id: uuid.UUID
    kind: Literal["riddle"]
    title: str
    description: str
    media: MediaRef | None
    solving_mode: SolvingMode
    validation_method: ValidationMethod
    max_attempts: int
    attempt_cooldown_seconds: int
    winner_policy: WinnerPolicy
    max_winners: int
    prize_description: str | None
    rewards: list[RewardSummary]
    participation_rules: str | None
    starts_at: datetime
    ends_at: datetime
    status: ChallengeStatus
    published_at: datetime | None
    results_published_at: datetime | None
    rules_version: int
    hints: list[ChallengeHintOut]
    my_participation: Participation | None


class ChallengeManagerView(ChallengeOut):
    all_hints: list[ManagedHint]
    normalization: AnswerNormalization
    answer_count: int
    participant_count: int
    pending_review_count: int
    reward_details: list[RewardDetail]
    version: int


class ChallengePage(_Out):
    data: list[ChallengeOut]
    page: PageInfo


class CreateTeamRequest(_Request):
    name: str = Field(min_length=2, max_length=40)


class ChallengeTeamOut(_Out):
    id: uuid.UUID
    challenge_id: uuid.UUID
    name: str
    captain: UserSummary | None
    members: list[UserSummary]
    conversation_id: uuid.UUID | None
    created_at: datetime


class ChallengeTeamPage(_Out):
    data: list[ChallengeTeamOut]
    page: PageInfo


class SubmitAnswerRequest(_Request):
    answer: str = Field(min_length=1, max_length=500)
    team_id: uuid.UUID | None = None


class SubmissionResult(_Out):
    """No feedback beyond the evaluation status (CHAL-005)."""

    submission_id: uuid.UUID
    attempt_no: int
    evaluation_status: EvaluationStatus
    attempts_remaining: int
    next_attempt_at: datetime | None
    is_provisional_winner: bool


class ChallengeSubmissionOut(_Out):
    """``ai_confidence`` and ``ai_rationale`` are filled for judges only."""

    id: uuid.UUID
    challenge_id: uuid.UUID
    submitted_by: UserSummary | None
    team_id: uuid.UUID | None
    attempt_no: int
    answer_text: str
    evaluation_status: EvaluationStatus
    evaluator: Literal["exact", "ai", "admin"] | None
    ai_confidence: float | None = None
    ai_rationale: str | None = None
    rules_version: int
    submitted_at: datetime
    evaluated_at: datetime | None


class JudgeSubmissionRequest(_Request):
    evaluation_status: Literal["correct", "incorrect", "void"]
    note: str | None = Field(default=None, max_length=500)


class AcceptedAnswerOut(_Out):
    id: uuid.UUID
    answer_display: str
    answer_normalized: str


class AcceptedAnswerList(_Out):
    data: list[AcceptedAnswerOut]


class ChallengeSubmissionPage(_Out):
    data: list[ChallengeSubmissionOut]
    page: PageInfo


class WinnerTeam(_Out):
    id: uuid.UUID
    name: str


class ChallengeWinnerOut(_Out):
    id: uuid.UUID
    rank: int
    user: UserSummary | None
    team: WinnerTeam | None
    status: Literal["provisional", "confirmed", "revoked"]
    determined_by: Literal["system", "admin"]
    determined_at: datetime


class ChallengeResults(_Out):
    challenge_id: uuid.UUID
    status: ChallengeStatus
    published: bool
    results_published_at: datetime | None
    participant_count: int
    winners: list[ChallengeWinnerOut]
