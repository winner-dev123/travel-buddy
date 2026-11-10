"""Group challenges: authoring, lifecycle, member views, submissions and winners (BL-5.01..5.03;
CHAL-001..003, CHAL-005, CHAL-006, CHAL-008..010, CHAL-012..014).

* Creating, editing, publishing and cancelling need ``challenges.manage`` in the group. That
  permission is premium-gated, so after the owner's premium lapses managers get
  ``entitlement_required`` (entitlement ``challenges.create``).
* Accepted answers are stored normalized in ``challenge_answers`` and never returned to members.
  Hints are filtered by ``release_at``; drafts are visible to managers only.
* Lifecycle (CHAL-003): ``draft`` → publish → ``scheduled`` → (scheduler at ``starts_at``)
  ``active`` → (at ``ends_at``) ``judging`` → results → ``completed``; or ``cancelled``. After
  activation only ``ends_at`` may be extended.
* Prizes: cash, cash equivalents, paid entry, wagers and random draws are rejected
  (``reward_not_permitted``); discount and promotional rewards need platform review before
  publishing (CHAL-013, CHAL-014).
* Team mode (CHAL-004): members create or join one team per challenge; the creator is the
  captain and the only submitter, attempts count per team, and every team gets a thread in
  messaging. Leaving the group takes a member out of their teams (captaincy passes on).
* Judging (CHAL-006, CHAL-007): judges decide any answer until results are published (audited,
  never their own); ``ai_assisted`` answers that don't match exactly go to the AI judge, whose
  verdict settles only confident, badge-only cases; the rest wait as ``needs_review``. Winners
  are re-derived after every decision, in submission order.
* Organizers (``challenges.judge`` holders, who can read the answers) don't take part.
* Submissions (CHAL-005, CHAL-009, CHAL-010) are idempotent and append-only. Each one locks the
  challenge row, so submissions to a challenge are serialized and first-correct order is commit
  order. Attempts and the cooldown are checked under that lock. A normalized exact match is
  judged at once; a correct answer becomes a provisional winner while the winner policy has
  slots left. Members get no feedback beyond the evaluation status.
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import delete, func, literal, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.pagination import CursorCodec, PageInfo
from app.core.security.principal import Principal
from app.core.time import Clock
from app.modules.challenges.domain import (
    DISPUTE_WINDOW,
    EDITABLE,
    IN_APP_REWARDS,
    MAX_OPEN_DISPUTES,
    REVIEWED_REWARDS,
    Normalization,
    Recipient,
    RewardInput,
    ai_outcome,
    attempt_block,
    can_transition,
    first_evaluation,
    next_attempt_at,
    normalize,
    pick_winners,
    prohibited_prize,
    reward_problems,
    status_at,
    winner_slots,
)
from app.modules.challenges.domain import (
    AIVerdict as AIVerdict,  # re-exported for the composition root
)
from app.modules.challenges.models import (
    Badge,
    ChallengeAnswer,
    ChallengeDispute,
    ChallengeHint,
    ChallengeParticipant,
    ChallengeReward,
    ChallengeSubmission,
    ChallengeTeam,
    ChallengeWinner,
    GroupChallenge,
    RewardFulfillment,
    UserBadge,
)
from app.modules.challenges.schemas import (
    AcceptedAnswerList,
    AcceptedAnswerOut,
    AnswerNormalization,
    BadgeSummary,
    ChallengeDisputeOut,
    ChallengeDisputePage,
    ChallengeHintOut,
    ChallengeManagerView,
    ChallengeOut,
    ChallengePage,
    ChallengeResults,
    ChallengeSubmissionOut,
    ChallengeSubmissionPage,
    ChallengeTeamOut,
    ChallengeTeamPage,
    ChallengeWinnerOut,
    CreateChallengeRequest,
    CreateDisputeRequest,
    CreateTeamRequest,
    FulfillmentTransitionRequest,
    HintList,
    JudgeSubmissionRequest,
    ManagedHint,
    MyRewardOut,
    MyRewardPage,
    Participation,
    ResolveDisputeRequest,
    RewardChallenge,
    RewardDetail,
    RewardFulfillmentOut,
    RewardFulfillmentPage,
    RewardSummary,
    SubmissionResult,
    SubmitAnswerRequest,
    UpdateChallengeRequest,
    UserBadgeList,
    UserBadgeOut,
    WinnerTeam,
)
from app.modules.challenges.secrets import (
    RewardSecretCipher as RewardSecretCipher,  # re-exported for the composition root
)
from app.modules.groups import service as groups
from app.modules.identity import service as identity
from app.modules.media import service as media
from app.modules.messaging import service as messaging
from app.modules.observability import service as observability
from app.modules.platform import service as platform
from app.modules.profiles import service as profiles
from app.modules.profiles.schemas import UserSummary
from app.modules.trust_safety import service as trust_safety

CREATE_ROUTE = "POST /v1/groups/{id}/challenges"
SUBMIT_ROUTE = "POST /v1/challenges/{id}/submissions"
MANAGE = "challenges.manage"
JUDGE = "challenges.judge"
STARTED_EVENT = "challenge.started"
CANCELLED_EVENT = "challenge.cancelled"
RESULTS_EVENT = "challenge.results_published"
REWARD_ISSUED_EVENT = "challenge.reward_issued"
LIFECYCLE_JOB = "challenges.lifecycle"
MEMBER_GONE_JOB = "challenges.member_gone"
AI_JUDGE_JOB = "challenges.ai_judge"
MEMBER_GONE_EVENTS = ("group.member_left", "group.member_removed")
TEAMS_OPEN = frozenset({"scheduled", "active"})
_RULE_FIELDS = frozenset(
    {
        "accepted_answers",
        "normalization",
        "starts_at",
        "ends_at",
        "max_attempts",
        "attempt_cooldown_seconds",
        "winner_policy",
        "max_winners",
    }
)


class AnswerJudge(Protocol):
    """The AI judge (ai_assistant, same layer), injected by the composition root."""

    async def __call__(
        self,
        *,
        user_id: uuid.UUID | None,
        title: str,
        description: str,
        accepted_answers: Sequence[str],
        answer: str,
    ) -> AIVerdict | None: ...


def _not_found() -> AppError:
    return AppError(ErrorCode.NOT_FOUND, "Challenge not found.")


def _invalid(field: str, message: str) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_FAILED,
        message,
        errors=[FieldError(field=field, code="invalid", message=message)],
    )


def _check_version(current: int, if_match: str | None) -> None:
    if if_match is None:
        raise AppError(ErrorCode.PRECONDITION_REQUIRED, "Send If-Match with the version you read.")
    if if_match.strip().strip('"') != str(current):
        raise AppError(ErrorCode.PRECONDITION_FAILED, "The challenge changed. Reload it first.")


def _prize_check(prize: str | None, rewards: Sequence[Any]) -> None:
    texts = [prize, *[r.title for r in rewards], *[r.description for r in rewards]]
    if prohibited_prize(*texts):
        raise AppError(
            ErrorCode.REWARD_NOT_PERMITTED,
            "Prizes can't be cash or cash equivalents, raffles, wagers or need paid entry.",
        )


class ChallengeService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        clock: Clock,
        cursors: CursorCodec,
        cipher: RewardSecretCipher | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._clock = clock
        self._cursors = cursors
        self._cipher = cipher

    # ─────────────────────────────── access ───────────────────────────────

    async def _member(
        self, session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID
    ) -> groups.MemberAccess:
        access = await groups.member_access(session, group_id, user_id, now=self._clock.now())
        if access is None:
            raise _not_found()
        return access

    @staticmethod
    def _require_manage(access: groups.MemberAccess) -> None:
        if MANAGE not in access.role_permissions:
            raise AppError(ErrorCode.FORBIDDEN, "Only group admins can manage challenges.")
        if MANAGE not in access.permissions:
            raise AppError(
                ErrorCode.ENTITLEMENT_REQUIRED,
                "Challenges need the group owner's Premium.",
                extensions={"entitlement": "challenges.create"},
            )

    async def _challenge(
        self, session: AsyncSession, challenge_id: uuid.UUID, user_id: uuid.UUID, *, lock: bool
    ) -> tuple[GroupChallenge, groups.MemberAccess]:
        row = await session.get(GroupChallenge, challenge_id, with_for_update=lock)
        if row is None:
            raise _not_found()
        now = self._clock.now()
        effective = status_at(row.status, row.starts_at, row.ends_at, now)
        if effective != row.status:
            # The scheduler may not have run yet (ticks are periodic): apply the move now.
            if lock:
                await _advance(session, row, now)
            else:
                row.status = effective
                session.expunge(row)  # display only; the next locked load persists it
        access = await self._member(session, row.group_id, user_id)
        if row.status == "draft" and MANAGE not in access.role_permissions:
            raise _not_found()  # drafts are not visible to members
        return row, access

    # ─────────────────────────────── output ───────────────────────────────

    async def _member_view(
        self, session: AsyncSession, row: GroupChallenge, user_id: uuid.UUID
    ) -> dict[str, Any]:
        now = self._clock.now()
        hints = (
            await session.scalars(
                select(ChallengeHint)
                .where(ChallengeHint.challenge_id == row.id)
                .order_by(ChallengeHint.sort_order)
            )
        ).all()
        rewards = (
            await session.scalars(
                select(ChallengeReward)
                .where(ChallengeReward.challenge_id == row.id)
                .order_by(ChallengeReward.created_at, ChallengeReward.id)
            )
        ).all()
        started = row.status not in ("draft", "scheduled", "cancelled")
        released = [
            ChallengeHintOut(
                id=h.id,
                sort_order=h.sort_order,
                body=h.body,
                released_at=max(h.release_at or row.starts_at, row.starts_at),
            )
            for h in hints
            if started and (h.release_at is None or h.release_at <= now)
        ]
        participant = await session.get(ChallengeParticipant, (row.id, user_id))
        participation = None
        if participant is not None:
            team = (
                await session.get(ChallengeTeam, participant.team_id)
                if participant.team_id
                else None
            )
            holder: ChallengeTeam | ChallengeParticipant = team or participant
            participation = Participation(
                attempts_used=holder.attempts_used,
                attempts_remaining=max(0, row.max_attempts - holder.attempts_used),
                next_attempt_at=next_attempt_at(
                    holder.last_attempt_at, row.attempt_cooldown_seconds, now
                ),
                team_id=participant.team_id,
                is_captain=team is not None and team.captain_id == user_id,
                status=participant.status,  # type: ignore[arg-type]
            )
        refs = await media.refs(session, [row.media_asset_id] if row.media_asset_id else [])
        return {
            "id": row.id,
            "group_id": row.group_id,
            "kind": row.kind,
            "title": row.title,
            "description": row.description,
            "media": refs.get(row.media_asset_id) if row.media_asset_id else None,
            "solving_mode": row.solving_mode,
            "validation_method": row.validation_method,
            "max_attempts": row.max_attempts,
            "attempt_cooldown_seconds": row.attempt_cooldown_seconds,
            "winner_policy": row.winner_policy,
            "max_winners": row.max_winners,
            "prize_description": row.prize_description,
            "rewards": [
                RewardSummary(
                    id=r.id,
                    reward_type=r.reward_type,  # type: ignore[arg-type]
                    title=r.title,
                    description=r.description,
                    sponsor_name=r.sponsor_name,
                    quantity=r.quantity,
                    terms_url=r.terms_url,
                )
                for r in rewards
            ],
            "participation_rules": row.participation_rules,
            "starts_at": row.starts_at,
            "ends_at": row.ends_at,
            "status": row.status,
            "published_at": row.published_at,
            "results_published_at": row.results_published_at,
            "rules_version": row.rules_version,
            "hints": released,
            "my_participation": participation,
            "_hints": hints,
            "_rewards": rewards,
        }

    async def _out(
        self, session: AsyncSession, row: GroupChallenge, user_id: uuid.UUID
    ) -> ChallengeOut:
        view = await self._member_view(session, row, user_id)
        view.pop("_hints")
        view.pop("_rewards")
        return ChallengeOut.model_validate(view)

    async def _manager_out(
        self, session: AsyncSession, row: GroupChallenge, user_id: uuid.UUID
    ) -> ChallengeManagerView:
        view = await self._member_view(session, row, user_id)
        hints, rewards = view.pop("_hints"), view.pop("_rewards")
        badges = {
            b.id: b
            for b in (
                await session.scalars(
                    select(Badge).where(Badge.id.in_([r.badge_id for r in rewards if r.badge_id]))
                )
            ).all()
        }
        answers = await session.scalar(
            select(func.count())
            .select_from(ChallengeAnswer)
            .where(ChallengeAnswer.challenge_id == row.id)
        )
        participants = await session.scalar(
            select(func.count())
            .select_from(ChallengeParticipant)
            .where(ChallengeParticipant.challenge_id == row.id)
        )
        pending = await session.scalar(
            select(func.count())
            .select_from(ChallengeSubmission)
            .where(
                ChallengeSubmission.challenge_id == row.id,
                ChallengeSubmission.evaluation_status.in_(("pending", "needs_review")),
            )
        )
        return ChallengeManagerView.model_validate(
            {
                **view,
                "all_hints": [
                    ManagedHint(
                        id=h.id, sort_order=h.sort_order, body=h.body, release_at=h.release_at
                    )
                    for h in hints
                ],
                "normalization": AnswerNormalization.model_validate(row.normalization),
                "answer_count": int(answers or 0),
                "participant_count": int(participants or 0),
                "pending_review_count": int(pending or 0),
                "reward_details": [
                    reward_detail(r, badges.get(r.badge_id) if r.badge_id else None)
                    for r in rewards
                ],
                "version": row.version,
            }
        )

    # ─────────────────────────────── authoring ───────────────────────────────

    async def _set_answers(
        self, session: AsyncSession, row: GroupChallenge, answers: Sequence[str]
    ) -> None:
        rules = Normalization.from_json(row.normalization)
        seen: dict[str, str] = {}
        for answer in answers:
            normalized = normalize(answer, rules)
            if not normalized:
                raise _invalid("/accepted_answers", "An accepted answer is empty once normalized.")
            seen.setdefault(normalized, answer.strip())
        await session.execute(delete(ChallengeAnswer).where(ChallengeAnswer.challenge_id == row.id))
        session.add_all(
            ChallengeAnswer(challenge_id=row.id, answer_display=display, answer_normalized=norm)
            for norm, display in seen.items()
        )

    async def _badge(self, session: AsyncSession, key: str, name: str) -> Badge:
        badge = await session.scalar(select(Badge).where(Badge.key == key))
        if badge is None:
            badge = Badge(key=key, name=name)
            session.add(badge)
            await session.flush()
        return badge

    async def create(
        self,
        principal: Principal,
        group_id: uuid.UUID,
        request: CreateChallengeRequest,
        *,
        idempotency_key: uuid.UUID,
    ) -> ChallengeManagerView:
        user_id = principal.user_id
        _prize_check(request.prize_description, request.rewards)
        for position, reward in enumerate(request.rewards):
            problems = reward_problems(RewardInput(**reward.model_dump()))
            if problems:
                raise _invalid(f"/rewards/{position}", problems[0])
        async with self._sessionmaker() as session, session.begin():
            replay = await platform.idempotency.claim(
                session,
                user_id=user_id,
                key=idempotency_key,
                route=CREATE_ROUTE,
                payload={"group": str(group_id), **request.model_dump(mode="json")},
            )
            if replay is not None:
                return ChallengeManagerView.model_validate(replay.body)
            access = await self._member(session, group_id, user_id)
            self._require_manage(access)
            if not access.group_active:
                raise AppError(ErrorCode.CONFLICT, "This group is archived.")
            if request.media_id is not None and not await media.usable_ids(
                session, user_id, [request.media_id], "challenge"
            ):
                raise _invalid("/media_id", "Upload the image as challenge media first.")
            now = self._clock.now()
            row = GroupChallenge(
                group_id=group_id,
                created_by=user_id,
                kind=request.kind,
                title=request.title.strip(),
                description=request.description.strip(),
                media_asset_id=request.media_id,
                solving_mode=request.solving_mode,
                validation_method=request.validation_method,
                normalization=Normalization.from_json(request.normalization.model_dump()).to_json(),
                max_attempts=request.max_attempts,
                attempt_cooldown_seconds=request.attempt_cooldown_seconds,
                winner_policy=request.winner_policy,
                max_winners=request.max_winners,
                prize_description=request.prize_description,
                participation_rules=request.participation_rules,
                starts_at=request.starts_at,
                ends_at=request.ends_at,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.flush()
            await self._set_answers(session, row, request.accepted_answers or [])
            session.add_all(
                ChallengeHint(
                    challenge_id=row.id, sort_order=i, body=h.body.strip(), release_at=h.release_at
                )
                for i, h in enumerate(request.hints)
            )
            for reward in request.rewards:
                badge = (
                    await self._badge(session, reward.badge_key, reward.title)
                    if reward.reward_type == "badge" and reward.badge_key
                    else None
                )
                reviewed = reward.reward_type in REVIEWED_REWARDS
                session.add(
                    ChallengeReward(
                        challenge_id=row.id,
                        reward_type=reward.reward_type,
                        title=reward.title.strip(),
                        description=reward.description,
                        badge_id=badge.id if badge else None,
                        sponsor_name=reward.sponsor_name,
                        quantity=reward.quantity,
                        eligibility_rules=reward.eligibility_rules,
                        terms_url=reward.terms_url,
                        fulfillment_owner=reward.fulfillment_owner,
                        requires_platform_review=reviewed,
                        review_status="pending" if reviewed else "not_required",
                        created_at=now,
                    )
                )
            await session.flush()
            out = await self._manager_out(session, row, user_id)
            await platform.idempotency.complete(
                session,
                user_id=user_id,
                key=idempotency_key,
                status=201,
                body=out.model_dump(mode="json"),
            )
            return out

    async def update(
        self,
        user_id: uuid.UUID,
        challenge_id: uuid.UUID,
        request: UpdateChallengeRequest,
        *,
        if_match: str | None,
    ) -> ChallengeManagerView:
        changes = request.model_dump(exclude_unset=True)
        if not changes:
            raise _invalid("/", "Change at least one field.")
        async with self._sessionmaker() as session, session.begin():
            row, access = await self._challenge(session, challenge_id, user_id, lock=True)
            self._require_manage(access)
            _check_version(row.version, if_match)
            if row.status not in EDITABLE:
                if row.status != "active" or set(changes) != {"ends_at"}:
                    raise AppError(
                        ErrorCode.CHALLENGE_LOCKED,
                        "After the start only the end time can be extended.",
                    )
                if changes["ends_at"] <= row.ends_at:
                    raise _invalid("/ends_at", "The end time can only be extended.")
            _prize_check(changes.get("prize_description"), [])
            if changes.get("media_id") is not None and not await media.usable_ids(
                session, user_id, [changes["media_id"]], "challenge"
            ):
                raise _invalid("/media_id", "Upload the image as challenge media first.")
            starts = changes.get("starts_at", row.starts_at)
            ends = changes.get("ends_at", row.ends_at)
            if starts >= ends:
                raise _invalid("/ends_at", "The end must come after the start.")
            for field in (
                "title",
                "description",
                "starts_at",
                "ends_at",
                "max_attempts",
                "attempt_cooldown_seconds",
                "winner_policy",
                "max_winners",
                "prize_description",
                "participation_rules",
            ):
                if field in changes:
                    setattr(row, field, changes[field])
            if "media_id" in changes:
                row.media_asset_id = changes["media_id"]
            if "normalization" in changes and changes["normalization"] is not None:
                row.normalization = Normalization.from_json(changes["normalization"]).to_json()
            if "accepted_answers" in changes and changes["accepted_answers"] is not None:
                await self._set_answers(session, row, changes["accepted_answers"])
            elif "normalization" in changes:
                displays = list(
                    await session.scalars(
                        select(ChallengeAnswer.answer_display).where(
                            ChallengeAnswer.challenge_id == row.id
                        )
                    )
                )
                await self._set_answers(session, row, displays)
            if _RULE_FIELDS & set(changes):
                row.rules_version += 1
            row.version += 1
            row.updated_at = self._clock.now()
            await session.flush()
            return await self._manager_out(session, row, user_id)

    async def publish(
        self, user_id: uuid.UUID, challenge_id: uuid.UUID, *, if_match: str | None
    ) -> ChallengeManagerView:
        async with self._sessionmaker() as session, session.begin():
            row, access = await self._challenge(session, challenge_id, user_id, lock=True)
            self._require_manage(access)
            _check_version(row.version, if_match)
            if row.status != "draft":
                raise AppError(ErrorCode.CONFLICT, "Only drafts can be published.")
            now = self._clock.now()
            if row.ends_at <= now:
                raise _invalid("/ends_at", "The challenge would already be over.")
            answers = await session.scalar(
                select(func.count())
                .select_from(ChallengeAnswer)
                .where(ChallengeAnswer.challenge_id == row.id)
            )
            if row.validation_method != "admin_review" and not answers:
                raise _invalid("/accepted_answers", "Add at least one accepted answer.")
            waiting = await session.scalar(
                select(func.count())
                .select_from(ChallengeReward)
                .where(
                    ChallengeReward.challenge_id == row.id,
                    ChallengeReward.requires_platform_review.is_(True),
                    ChallengeReward.review_status != "approved",
                )
            )
            if waiting:
                raise AppError(
                    ErrorCode.CONFLICT,
                    "Discount and promotional rewards need platform review before publishing.",
                )
            row.published_at = now
            row.status = status_at("scheduled", row.starts_at, row.ends_at, now)
            row.version += 1
            row.updated_at = now
            if row.status == "active":
                await _record_started(session, row)
            await session.flush()
            return await self._manager_out(session, row, user_id)

    async def cancel(
        self, user_id: uuid.UUID, challenge_id: uuid.UUID, reason: str
    ) -> ChallengeManagerView:
        async with self._sessionmaker() as session, session.begin():
            row, access = await self._challenge(session, challenge_id, user_id, lock=True)
            self._require_manage(access)
            if row.status in ("completed", "cancelled"):
                raise AppError(ErrorCode.CONFLICT, "This challenge is already closed.")
            was_published = row.status != "draft"
            row.status = "cancelled"
            row.cancel_reason = reason.strip()
            row.version += 1
            row.updated_at = self._clock.now()
            if was_published:
                platform.record_event(
                    session,
                    aggregate_type="challenge",
                    aggregate_id=row.id,
                    event_type=CANCELLED_EVENT,
                    payload={
                        "challenge_id": str(row.id),
                        "group_id": str(row.group_id),
                        "title": row.title,
                        "recipient_ids": [
                            str(m) for m in await groups.member_ids(session, row.group_id)
                        ],
                    },
                )
            await session.flush()
            return await self._manager_out(session, row, user_id)

    # ─────────────────────────────── reads ───────────────────────────────

    async def get(self, user_id: uuid.UUID, challenge_id: uuid.UUID) -> ChallengeOut:
        async with self._sessionmaker() as session:
            row, _ = await self._challenge(session, challenge_id, user_id, lock=False)
            return await self._out(session, row, user_id)

    async def manage(self, user_id: uuid.UUID, challenge_id: uuid.UUID) -> ChallengeManagerView:
        async with self._sessionmaker() as session:
            row, access = await self._challenge(session, challenge_id, user_id, lock=False)
            if MANAGE not in access.role_permissions:
                raise AppError(ErrorCode.FORBIDDEN, "Only group admins can manage challenges.")
            return await self._manager_out(session, row, user_id)

    async def hints(self, user_id: uuid.UUID, challenge_id: uuid.UUID) -> HintList:
        return HintList(data=(await self.get(user_id, challenge_id)).hints)

    async def list_for_group(
        self,
        user_id: uuid.UUID,
        group_id: uuid.UUID,
        *,
        statuses: Sequence[str],
        cursor: str | None,
        limit: int,
    ) -> ChallengePage:
        async with self._sessionmaker() as session:
            access = await self._member(session, group_id, user_id)
            conditions: list[Any] = [GroupChallenge.group_id == group_id]
            if MANAGE not in access.role_permissions:
                conditions.append(GroupChallenge.status != "draft")
            if statuses:
                conditions.append(GroupChallenge.status.in_(list(statuses)))
            filters = {"g": str(group_id), "s": sorted(statuses)}
            if cursor is not None:
                decoded = self._cursors.decode(cursor, scope="challenges")
                if decoded.get("f") != filters:
                    raise AppError(ErrorCode.INVALID_CURSOR, "The cursor belongs to another query.")
                conditions.append(
                    tuple_(GroupChallenge.starts_at, GroupChallenge.id)
                    < tuple_(
                        literal(datetime.fromisoformat(decoded["t"])),
                        literal(uuid.UUID(decoded["i"])),
                    )
                )
            rows = list(
                (
                    await session.scalars(
                        select(GroupChallenge)
                        .where(*conditions)
                        .order_by(GroupChallenge.starts_at.desc(), GroupChallenge.id.desc())
                        .limit(limit + 1)
                    )
                ).all()
            )
            more = len(rows) > limit
            rows = rows[:limit]
            data = [await self._out(session, row, user_id) for row in rows]
        next_cursor = (
            self._cursors.encode(
                {"f": filters, "t": rows[-1].starts_at.isoformat(), "i": str(rows[-1].id)},
                scope="challenges",
            )
            if more and rows
            else None
        )
        return ChallengePage(data=data, page=PageInfo(next_cursor=next_cursor))

    # ─────────────────────────────── teams ───────────────────────────────

    async def _teams_out(
        self, session: AsyncSession, teams: Sequence[ChallengeTeam]
    ) -> list[ChallengeTeamOut]:
        if not teams:
            return []
        members = (
            await session.execute(
                select(ChallengeParticipant.team_id, ChallengeParticipant.user_id)
                .where(
                    ChallengeParticipant.team_id.in_([t.id for t in teams]),
                    ChallengeParticipant.status == "active",
                )
                .order_by(ChallengeParticipant.joined_at, ChallengeParticipant.user_id)
            )
        ).all()
        users = await profiles.authors(
            session, list({u for _, u in members} | {t.captain_id for t in teams if t.captain_id})
        )
        by_team: dict[uuid.UUID, list[UserSummary]] = defaultdict(list)
        for team_id, member_id in members:
            if member_id in users:
                by_team[team_id].append(profiles.user_summary(users[member_id]))
        return [
            ChallengeTeamOut(
                id=t.id,
                challenge_id=t.challenge_id,
                name=t.name,
                captain=profiles.user_summary(users[t.captain_id])
                if t.captain_id in users
                else None,
                members=by_team[t.id],
                conversation_id=t.conversation_id,
                created_at=t.created_at,
            )
            for t in teams
        ]

    async def list_teams(
        self, user_id: uuid.UUID, challenge_id: uuid.UUID, *, cursor: str | None, limit: int
    ) -> ChallengeTeamPage:
        async with self._sessionmaker() as session:
            row, _ = await self._challenge(session, challenge_id, user_id, lock=False)
            conditions: list[Any] = [ChallengeTeam.challenge_id == row.id]
            filters = {"c": str(row.id)}
            if cursor is not None:
                decoded = self._cursors.decode(cursor, scope="challenge-teams")
                if decoded.get("f") != filters:
                    raise AppError(ErrorCode.INVALID_CURSOR, "The cursor belongs to another query.")
                conditions.append(
                    tuple_(ChallengeTeam.created_at, ChallengeTeam.id)
                    > tuple_(
                        literal(datetime.fromisoformat(decoded["t"])),
                        literal(uuid.UUID(decoded["i"])),
                    )
                )
            teams = list(
                (
                    await session.scalars(
                        select(ChallengeTeam)
                        .where(*conditions)
                        .order_by(ChallengeTeam.created_at, ChallengeTeam.id)
                        .limit(limit + 1)
                    )
                ).all()
            )
            more = len(teams) > limit
            teams = teams[:limit]
            data = await self._teams_out(session, teams)
        next_cursor = (
            self._cursors.encode(
                {"f": filters, "t": teams[-1].created_at.isoformat(), "i": str(teams[-1].id)},
                scope="challenge-teams",
            )
            if more and teams
            else None
        )
        return ChallengeTeamPage(data=data, page=PageInfo(next_cursor=next_cursor))

    async def create_team(
        self, user_id: uuid.UUID, challenge_id: uuid.UUID, request: CreateTeamRequest
    ) -> ChallengeTeamOut:
        """The creator becomes the captain, the only one who submits (CHAL-004)."""
        async with self._sessionmaker() as session, session.begin():
            row, _ = await self._challenge(session, challenge_id, user_id, lock=True)
            _require_open_teams(row)
            participant = await self._teamless(session, row, user_id)
            name = " ".join(request.name.split())
            if len(name) < 2:
                raise _invalid("/name", "Give the team a name.")
            taken = await session.scalar(
                select(ChallengeTeam.id).where(
                    ChallengeTeam.challenge_id == row.id,
                    func.lower(ChallengeTeam.name) == name.lower(),
                )
            )
            if taken is not None:
                raise AppError(ErrorCode.CONFLICT, "Another team already uses that name.")
            now = self._clock.now()
            team = ChallengeTeam(challenge_id=row.id, name=name, captain_id=user_id, created_at=now)
            session.add(team)
            await session.flush()
            team.conversation_id = await messaging.create_team_conversation(
                session, team.id, user_id
            )
            self._enrol(session, row, user_id, participant, team, now)
            await session.flush()
            [out] = await self._teams_out(session, [team])
            return out

    async def join_team(
        self, user_id: uuid.UUID, challenge_id: uuid.UUID, team_id: uuid.UUID
    ) -> ChallengeTeamOut:
        """One team per participant per challenge; joining your own team again is a no-op."""
        async with self._sessionmaker() as session, session.begin():
            row, _ = await self._challenge(session, challenge_id, user_id, lock=True)
            team = await session.get(ChallengeTeam, team_id, with_for_update=True)
            if team is None or team.challenge_id != row.id:
                raise AppError(ErrorCode.NOT_FOUND, "Team not found.")
            current = await session.get(ChallengeParticipant, (row.id, user_id))
            if current is None or current.team_id != team.id:
                _require_open_teams(row)
                participant = await self._teamless(session, row, user_id)
                self._enrol(session, row, user_id, participant, team, self._clock.now())
                if team.captain_id is None:  # a team whose captain left gets one back
                    team.captain_id = user_id
                if team.conversation_id is not None:
                    await messaging.add_group_member(
                        session, team.conversation_id, user_id, from_join=False
                    )
                await session.flush()
            [out] = await self._teams_out(session, [team])
            return out

    @staticmethod
    async def _teamless(
        session: AsyncSession, row: GroupChallenge, user_id: uuid.UUID
    ) -> ChallengeParticipant | None:
        participant = await session.get(
            ChallengeParticipant, (row.id, user_id), with_for_update=True
        )
        if participant is not None and participant.status != "active":
            raise AppError(ErrorCode.FORBIDDEN, "You can't take part in this challenge.")
        if participant is not None and participant.team_id is not None:
            raise AppError(ErrorCode.CONFLICT, "You're already in a team for this challenge.")
        return participant

    @staticmethod
    def _enrol(
        session: AsyncSession,
        row: GroupChallenge,
        user_id: uuid.UUID,
        participant: ChallengeParticipant | None,
        team: ChallengeTeam,
        now: datetime,
    ) -> None:
        if participant is None:
            session.add(
                ChallengeParticipant(
                    challenge_id=row.id,
                    user_id=user_id,
                    team_id=team.id,
                    joined_at=now,
                    attempts_used=0,
                    status="active",
                )
            )
        else:
            participant.team_id = team.id

    # ─────────────────────────────── submissions ───────────────────────────────

    async def submit(
        self,
        user_id: uuid.UUID,
        challenge_id: uuid.UUID,
        request: SubmitAnswerRequest,
        *,
        idempotency_key: uuid.UUID,
    ) -> SubmissionResult:
        async with self._sessionmaker() as session, session.begin():
            replay = await platform.idempotency.claim(
                session,
                user_id=user_id,
                key=idempotency_key,
                route=SUBMIT_ROUTE,
                payload={"challenge": str(challenge_id), **request.model_dump(mode="json")},
            )
            if replay is not None:
                return SubmissionResult.model_validate(replay.body)
            # The row lock serializes submissions to this challenge (CHAL-009).
            row, access = await self._challenge(session, challenge_id, user_id, lock=True)
            if JUDGE in access.role_permissions:
                raise AppError(
                    ErrorCode.FORBIDDEN, "Organizers can't take part in their own challenge."
                )
            now = self._clock.now()
            if row.status != "active" or not row.starts_at <= now < row.ends_at:
                raise AppError(
                    ErrorCode.CHALLENGE_NOT_ACTIVE,
                    "This challenge isn't taking answers right now.",
                    extensions={
                        "challenge_status": row.status,
                        "starts_at": row.starts_at.isoformat(),
                        "ends_at": row.ends_at.isoformat(),
                    },
                )
            normalized = normalize(request.answer, Normalization.from_json(row.normalization))
            if not normalized:
                raise _invalid("/answer", "Type an answer.")
            participant = await session.get(
                ChallengeParticipant, (row.id, user_id), with_for_update=True
            )
            if participant is not None and participant.status != "active":
                raise AppError(ErrorCode.FORBIDDEN, "You can't take part in this challenge.")
            team: ChallengeTeam | None = None
            if row.solving_mode == "team":
                team = await _captain_team(session, participant, user_id, request.team_id)
            elif participant is None:
                participant = ChallengeParticipant(
                    challenge_id=row.id,
                    user_id=user_id,
                    joined_at=now,
                    attempts_used=0,
                    status="active",
                )
                session.add(participant)
            holder: ChallengeTeam | ChallengeParticipant = team or participant  # type: ignore[assignment]
            solved = await session.scalar(
                select(ChallengeSubmission.id)
                .where(
                    ChallengeSubmission.challenge_id == row.id,
                    (
                        ChallengeSubmission.team_id == team.id
                        if team is not None
                        else ChallengeSubmission.submitted_by == user_id
                    ),
                    ChallengeSubmission.evaluation_status == "correct",
                )
                .limit(1)
            )
            if solved is not None:
                raise AppError(ErrorCode.CONFLICT, "You already solved this challenge.")
            _check_attempt(row, holder, now)
            accepted = set(
                await session.scalars(
                    select(ChallengeAnswer.answer_normalized).where(
                        ChallengeAnswer.challenge_id == row.id
                    )
                )
            )
            evaluation, evaluator = first_evaluation(row.validation_method, normalized in accepted)
            holder.attempts_used += 1
            holder.last_attempt_at = now
            submission = ChallengeSubmission(
                challenge_id=row.id,
                submitted_by=user_id,
                team_id=team.id if team is not None else None,
                attempt_no=holder.attempts_used,
                answer_text=request.answer.strip(),
                answer_normalized=normalized,
                idempotency_key=idempotency_key,
                evaluation_status=evaluation,
                evaluator=evaluator,
                rules_version=row.rules_version,
                submitted_at=now,
                evaluated_at=now if evaluator else None,
            )
            session.add(submission)
            await session.flush()
            if evaluation == "pending" and row.validation_method == "ai_assisted":
                await platform.enqueue(
                    session,
                    queue="default",
                    kind=AI_JUDGE_JOB,
                    payload={"submission_id": str(submission.id)},
                    dedupe_key=f"{AI_JUDGE_JOB}:{submission.id}",
                )
            won = False
            if evaluation == "correct":
                await _sync_winners(session, row, now)
                # Under admin_selects a correct answer is only a candidate until judges pick.
                won = (
                    row.winner_policy != "admin_selects"
                    and (
                        await session.scalar(
                            select(func.count())
                            .select_from(ChallengeWinner)
                            .where(
                                ChallengeWinner.submission_id == submission.id,
                                ChallengeWinner.status != "revoked",
                            )
                        )
                        or 0
                    )
                    > 0
                )
            remaining = max(0, row.max_attempts - holder.attempts_used)
            out = SubmissionResult(
                submission_id=submission.id,
                attempt_no=submission.attempt_no,
                evaluation_status=evaluation,  # type: ignore[arg-type]
                attempts_remaining=remaining,
                next_attempt_at=(
                    next_attempt_at(now, row.attempt_cooldown_seconds, now)
                    if remaining and evaluation != "correct"
                    else None
                ),
                is_provisional_winner=won,
            )
            await platform.idempotency.complete(
                session,
                user_id=user_id,
                key=idempotency_key,
                status=201,
                body=out.model_dump(mode="json"),
            )
            return out

    async def _submissions_out(
        self, session: AsyncSession, rows: Sequence[ChallengeSubmission], *, judge: bool
    ) -> list[ChallengeSubmissionOut]:
        """AI confidence and rationale are for judges only (CHAL-008)."""
        users = await profiles.authors(session, [r.submitted_by for r in rows if r.submitted_by])
        return [
            ChallengeSubmissionOut(
                id=r.id,
                challenge_id=r.challenge_id,
                submitted_by=(
                    profiles.user_summary(users[r.submitted_by])
                    if r.submitted_by in users
                    else None
                ),
                team_id=r.team_id,
                attempt_no=r.attempt_no,
                answer_text=r.answer_text,
                evaluation_status=r.evaluation_status,  # type: ignore[arg-type]
                evaluator=r.evaluator,  # type: ignore[arg-type]
                ai_confidence=(
                    float(r.ai_confidence) if judge and r.ai_confidence is not None else None
                ),
                ai_rationale=r.ai_rationale if judge else None,
                rules_version=r.rules_version,
                submitted_at=r.submitted_at,
                evaluated_at=r.evaluated_at,
            )
            for r in rows
        ]

    async def submissions(
        self,
        user_id: uuid.UUID,
        challenge_id: uuid.UUID,
        *,
        scope: str,
        evaluation_status: str | None,
        cursor: str | None,
        limit: int,
    ) -> ChallengeSubmissionPage:
        async with self._sessionmaker() as session:
            row, access = await self._challenge(session, challenge_id, user_id, lock=False)
            judge = JUDGE in access.permissions
            if scope == "all" and not judge:
                raise AppError(ErrorCode.FORBIDDEN, "Only judges can see every submission.")
            conditions: list[Any] = [ChallengeSubmission.challenge_id == row.id]
            if scope == "mine":
                mine = await session.get(ChallengeParticipant, (row.id, user_id))
                conditions.append(
                    or_(
                        ChallengeSubmission.submitted_by == user_id,
                        ChallengeSubmission.team_id == mine.team_id,
                    )
                    if mine is not None and mine.team_id is not None
                    else ChallengeSubmission.submitted_by == user_id
                )
            if evaluation_status is not None:
                conditions.append(ChallengeSubmission.evaluation_status == evaluation_status)
            filters = {"c": str(row.id), "s": scope, "e": evaluation_status}
            if cursor is not None:
                decoded = self._cursors.decode(cursor, scope="challenge-submissions")
                if decoded.get("f") != filters:
                    raise AppError(ErrorCode.INVALID_CURSOR, "The cursor belongs to another query.")
                conditions.append(
                    tuple_(ChallengeSubmission.submitted_at, ChallengeSubmission.id)
                    > tuple_(
                        literal(datetime.fromisoformat(decoded["t"])),
                        literal(uuid.UUID(decoded["i"])),
                    )
                )
            rows = list(
                (
                    await session.scalars(
                        select(ChallengeSubmission)
                        .where(*conditions)
                        .order_by(ChallengeSubmission.submitted_at, ChallengeSubmission.id)
                        .limit(limit + 1)
                    )
                ).all()
            )
            more = len(rows) > limit
            rows = rows[:limit]
            data = await self._submissions_out(session, rows, judge=judge)
        next_cursor = (
            self._cursors.encode(
                {"f": filters, "t": rows[-1].submitted_at.isoformat(), "i": str(rows[-1].id)},
                scope="challenge-submissions",
            )
            if more and rows
            else None
        )
        return ChallengeSubmissionPage(data=data, page=PageInfo(next_cursor=next_cursor))

    # ─────────────────────────────── judging ───────────────────────────────

    async def judge_submission(
        self,
        user_id: uuid.UUID,
        challenge_id: uuid.UUID,
        submission_id: uuid.UUID,
        request: JudgeSubmissionRequest,
    ) -> ChallengeSubmissionOut:
        """A judge's decision on any submission until results are published; audited, never on
        one's own (or one's team's) answer (CHAL-006, CHAL-009, T-CHAL-04)."""
        async with self._sessionmaker() as session, session.begin():
            row, access = await self._challenge(session, challenge_id, user_id, lock=True)
            if JUDGE not in access.permissions:
                raise AppError(ErrorCode.FORBIDDEN, "Only judges can judge answers.")
            if row.results_published_at is not None or row.status in ("completed", "cancelled"):
                raise AppError(ErrorCode.CONFLICT, "Results are final. Raise a dispute instead.")
            submission = await session.get(ChallengeSubmission, submission_id, with_for_update=True)
            if submission is None or submission.challenge_id != row.id:
                raise AppError(ErrorCode.NOT_FOUND, "Submission not found.")
            mine = await session.get(ChallengeParticipant, (row.id, user_id))
            if submission.submitted_by == user_id or (
                submission.team_id is not None
                and mine is not None
                and mine.team_id == submission.team_id
            ):
                raise AppError(ErrorCode.FORBIDDEN, "You can't judge your own answer.")
            before = submission.evaluation_status
            now = self._clock.now()
            submission.evaluation_status = request.evaluation_status
            submission.evaluator = "admin"
            submission.evaluated_by = user_id
            submission.evaluated_at = now
            observability.audit(
                session,
                actor_id=user_id,
                actor_type="user",
                action="challenge.submission_judged",
                resource_type="challenge_submission",
                resource_id=submission.id,
                metadata={
                    "challenge_id": str(row.id),
                    "from": before,
                    "to": request.evaluation_status,
                    "note": request.note,
                },
            )
            await session.flush()
            if "correct" in (before, request.evaluation_status):
                await _sync_winners(session, row, now)
            [out] = await self._submissions_out(session, [submission], judge=True)
            return out

    async def answers(self, user_id: uuid.UUID, challenge_id: uuid.UUID) -> AcceptedAnswerList:
        """Accepted answers for judges only; every read is audited (CHAL-008)."""
        async with self._sessionmaker() as session, session.begin():
            row, access = await self._challenge(session, challenge_id, user_id, lock=False)
            if JUDGE not in access.permissions:
                raise AppError(ErrorCode.FORBIDDEN, "Only judges can see the answers.")
            rows = (
                await session.scalars(
                    select(ChallengeAnswer)
                    .where(ChallengeAnswer.challenge_id == row.id)
                    .order_by(ChallengeAnswer.created_at, ChallengeAnswer.id)
                )
            ).all()
            observability.audit(
                session,
                actor_id=user_id,
                actor_type="user",
                action="challenge.answers_viewed",
                resource_type="challenge",
                resource_id=row.id,
            )
            return AcceptedAnswerList(
                data=[
                    AcceptedAnswerOut(
                        id=a.id,
                        answer_display=a.answer_display,
                        answer_normalized=a.answer_normalized,
                    )
                    for a in rows
                ]
            )

    async def _winners_out(
        self, session: AsyncSession, winners: Sequence[ChallengeWinner]
    ) -> list[ChallengeWinnerOut]:
        users = await profiles.authors(session, [w.user_id for w in winners if w.user_id])
        team_ids = [w.team_id for w in winners if w.team_id]
        teams = {
            t.id: t
            for t in (
                await session.scalars(select(ChallengeTeam).where(ChallengeTeam.id.in_(team_ids)))
            ).all()
        }
        return [
            ChallengeWinnerOut(
                id=w.id,
                rank=w.rank,
                user=profiles.user_summary(users[w.user_id]) if w.user_id in users else None,
                team=(
                    WinnerTeam(id=teams[w.team_id].id, name=teams[w.team_id].name)
                    if w.team_id in teams
                    else None
                ),
                status=w.status,  # type: ignore[arg-type]
                determined_by=w.determined_by,  # type: ignore[arg-type]
                determined_at=w.determined_at,
            )
            for w in winners
        ]

    async def results(self, user_id: uuid.UUID, challenge_id: uuid.UUID) -> ChallengeResults:
        """Members see confirmed winners once results are published; judges see provisional and
        revoked winners at any time (CHAL-011)."""
        async with self._sessionmaker() as session:
            row, access = await self._challenge(session, challenge_id, user_id, lock=False)
            judge = JUDGE in access.permissions
            published = row.results_published_at is not None
            winners: list[ChallengeWinner] = []
            if judge or published:
                query = select(ChallengeWinner).where(ChallengeWinner.challenge_id == row.id)
                if not judge:
                    query = query.where(ChallengeWinner.status == "confirmed")
                winners = list(
                    (
                        await session.scalars(
                            query.order_by(ChallengeWinner.rank, ChallengeWinner.determined_at)
                        )
                    ).all()
                )
            participants = await session.scalar(
                select(func.count())
                .select_from(ChallengeParticipant)
                .where(ChallengeParticipant.challenge_id == row.id)
            )
            out = await self._winners_out(session, winners)
        return ChallengeResults(
            challenge_id=row.id,
            status=row.status,  # type: ignore[arg-type]
            published=published,
            results_published_at=row.results_published_at,
            participant_count=int(participants or 0),
            winners=out,
        )

    @staticmethod
    def _require_judge(access: groups.MemberAccess) -> None:
        if JUDGE not in access.permissions:
            raise AppError(ErrorCode.FORBIDDEN, "Only judges can do that.")

    async def winner_action(
        self,
        user_id: uuid.UUID,
        challenge_id: uuid.UUID,
        winner_id: uuid.UUID,
        action: str,
        note: str | None,
    ) -> ChallengeWinnerOut:
        """Confirm or revoke a winner before results are published (CHAL-010; audited). Under
        ``admin_selects`` confirming picks a candidate, up to ``max_winners``; revoking under the
        other policies lets the next correct answer move up."""
        async with self._sessionmaker() as session, session.begin():
            row, access = await self._challenge(session, challenge_id, user_id, lock=True)
            self._require_judge(access)
            _require_unpublished(row)
            winner = await session.get(ChallengeWinner, winner_id, with_for_update=True)
            if winner is None or winner.challenge_id != row.id:
                raise AppError(ErrorCode.NOT_FOUND, "Winner not found.")
            now = self._clock.now()
            if action == "confirm":
                if winner.status == "revoked":
                    raise AppError(ErrorCode.CONFLICT, "A revoked winner can't be confirmed.")
                if winner.status == "provisional":
                    if row.winner_policy == "admin_selects":
                        picked = await session.scalar(
                            select(func.count())
                            .select_from(ChallengeWinner)
                            .where(
                                ChallengeWinner.challenge_id == row.id,
                                ChallengeWinner.status == "confirmed",
                            )
                        )
                        if int(picked or 0) >= row.max_winners:
                            raise AppError(
                                ErrorCode.CONFLICT,
                                f"Up to {row.max_winners} winner(s) can be picked.",
                            )
                        winner.determined_by = "admin"
                    winner.status = "confirmed"
                    winner.confirmed_by = user_id
            elif winner.status != "revoked":
                winner.status = "revoked"
            observability.audit(
                session,
                actor_id=user_id,
                actor_type="user",
                action=f"challenge.winner_{'confirmed' if action == 'confirm' else 'revoked'}",
                resource_type="challenge_winner",
                resource_id=winner.id,
                metadata={"challenge_id": str(row.id), "note": note},
            )
            await session.flush()
            if action == "revoke":
                await _sync_winners(session, row, now)
            await session.refresh(winner)
            [out] = await self._winners_out(session, [winner])
            return out

    async def publish_results(
        self, user_id: uuid.UUID, challenge_id: uuid.UUID
    ) -> ChallengeResults:
        """Final winners, badges, reward fulfillments and a note to the group (CHAL-011, CHAL-012,
        CHAL-015). Needs every answer decided and no open dispute."""
        async with self._sessionmaker() as session, session.begin():
            row, access = await self._challenge(session, challenge_id, user_id, lock=True)
            self._require_judge(access)
            if row.results_published_at is not None:
                raise AppError(ErrorCode.CONFLICT, "Results are already published.")
            if row.status not in ("active", "judging"):
                raise AppError(ErrorCode.CONFLICT, "Results come once the challenge has run.")
            undecided = await session.scalar(
                select(func.count())
                .select_from(ChallengeSubmission)
                .where(
                    ChallengeSubmission.challenge_id == row.id,
                    ChallengeSubmission.evaluation_status.in_(("pending", "needs_review")),
                )
            )
            if undecided:
                raise AppError(ErrorCode.CONFLICT, "Some answers still need a decision.")
            disputed = await session.scalar(
                select(func.count())
                .select_from(ChallengeDispute)
                .where(ChallengeDispute.challenge_id == row.id, ChallengeDispute.status == "open")
            )
            if disputed:
                raise AppError(ErrorCode.CONFLICT, "Resolve the open disputes first.")
            now = self._clock.now()
            live = list(
                (
                    await session.scalars(
                        select(ChallengeWinner)
                        .where(
                            ChallengeWinner.challenge_id == row.id,
                            ChallengeWinner.status != "revoked",
                        )
                        .order_by(ChallengeWinner.rank)
                    )
                ).all()
            )
            for winner in live:
                if winner.status != "provisional":
                    continue
                if row.winner_policy == "admin_selects":
                    winner.status = "revoked"  # candidates the judges didn't pick
                else:
                    winner.status = "confirmed"
                    winner.confirmed_by = user_id
            final = [w for w in live if w.status == "confirmed"]
            await session.flush()
            for offset, winner in enumerate(final):  # compact ranks: park, then renumber
                winner.rank = 1000 + offset
            await session.flush()
            for rank, winner in enumerate(final, start=1):
                winner.rank = rank
            await session.flush()
            await self._award_rewards(session, row, final, now)
            row.status = "completed"
            row.results_published_at = now
            row.version += 1
            row.updated_at = now
            observability.audit(
                session,
                actor_id=user_id,
                actor_type="user",
                action="challenge.results_published",
                resource_type="challenge",
                resource_id=row.id,
                metadata={"winners": len(final)},
            )
            platform.record_event(
                session,
                aggregate_type="challenge",
                aggregate_id=row.id,
                event_type=RESULTS_EVENT,
                payload={
                    "challenge_id": str(row.id),
                    "group_id": str(row.group_id),
                    "title": row.title,
                    "recipient_ids": [
                        str(m) for m in await groups.member_ids(session, row.group_id)
                    ],
                },
            )
            await session.flush()
        return await self.results(user_id, challenge_id)

    async def _award_rewards(
        self,
        session: AsyncSession,
        row: GroupChallenge,
        winners: Sequence[ChallengeWinner],
        now: datetime,
    ) -> None:
        """Each reward goes to the top ``quantity`` winners: badges and achievements straight to
        the people (every member of a winning team), real-world rewards into fulfillment for the
        winner or the team captain (CHAL-012, CHAL-015)."""
        rewards = (
            await session.scalars(
                select(ChallengeReward)
                .where(ChallengeReward.challenge_id == row.id)
                .order_by(ChallengeReward.created_at, ChallengeReward.id)
            )
        ).all()
        for reward in rewards:
            recipients = list(winners[: reward.quantity])
            if reward.reward_type in IN_APP_REWARDS:
                if reward.badge_id is None:  # an achievement: an in-app badge of its own
                    reward.badge_id = (
                        await self._badge(session, f"achievement-{reward.id}", reward.title)
                    ).id
                for winner in recipients:
                    for person in await _winner_people(session, winner):
                        await session.execute(
                            insert(UserBadge)
                            .values(
                                user_id=person,
                                badge_id=reward.badge_id,
                                source_type="challenge",
                                source_id=row.id,
                                awarded_at=now,
                            )
                            .on_conflict_do_nothing()
                        )
            elif reward.review_status == "approved":
                for winner in recipients:
                    recipient = winner.user_id
                    if winner.team_id is not None:
                        team = await session.get(ChallengeTeam, winner.team_id)
                        recipient = team.captain_id if team else None
                    session.add(
                        RewardFulfillment(
                            challenge_id=row.id,
                            challenge_reward_id=reward.id,
                            winner_id=winner.id,
                            recipient_user_id=recipient,
                            status="pending",
                            created_at=now,
                            updated_at=now,
                        )
                    )
        await session.flush()

    # ─────────────────────────────── disputes ───────────────────────────────

    async def _disputes_out(
        self, session: AsyncSession, rows: Sequence[ChallengeDispute]
    ) -> list[ChallengeDisputeOut]:
        users = await profiles.authors(session, [d.raised_by for d in rows if d.raised_by])
        return [
            ChallengeDisputeOut(
                id=d.id,
                challenge_id=d.challenge_id,
                raised_by=profiles.user_summary(users[d.raised_by])
                if d.raised_by in users
                else None,
                submission_id=d.submission_id,
                reason=d.reason,
                status=d.status,  # type: ignore[arg-type]
                resolution_note=d.resolution_note,
                created_at=d.created_at,
                resolved_at=d.resolved_at,
            )
            for d in rows
        ]

    async def create_dispute(
        self, user_id: uuid.UUID, challenge_id: uuid.UUID, request: CreateDisputeRequest
    ) -> ChallengeDisputeOut:
        """Participants dispute a judgement or the results (CHAL-016)."""
        async with self._sessionmaker() as session, session.begin():
            row, _ = await self._challenge(session, challenge_id, user_id, lock=False)
            participant = await session.get(ChallengeParticipant, (row.id, user_id))
            if participant is None:
                raise AppError(ErrorCode.FORBIDDEN, "Only participants can raise a dispute.")
            now = self._clock.now()
            if row.status in ("draft", "scheduled", "cancelled"):
                raise AppError(ErrorCode.CONFLICT, "There is nothing to dispute yet.")
            if row.results_published_at and now > row.results_published_at + DISPUTE_WINDOW:
                raise AppError(ErrorCode.CONFLICT, "The time to dispute these results is over.")
            if request.submission_id is not None:
                submission = await session.get(ChallengeSubmission, request.submission_id)
                if (
                    submission is None
                    or submission.challenge_id != row.id
                    or not (
                        submission.submitted_by == user_id
                        or (
                            submission.team_id is not None
                            and submission.team_id == participant.team_id
                        )
                    )
                ):
                    raise AppError(ErrorCode.NOT_FOUND, "Submission not found.")
            open_count = await session.scalar(
                select(func.count())
                .select_from(ChallengeDispute)
                .where(
                    ChallengeDispute.challenge_id == row.id,
                    ChallengeDispute.raised_by == user_id,
                    ChallengeDispute.status == "open",
                )
            )
            if int(open_count or 0) >= MAX_OPEN_DISPUTES:
                raise AppError(ErrorCode.CONFLICT, "You already have open disputes here.")
            dispute = ChallengeDispute(
                challenge_id=row.id,
                raised_by=user_id,
                submission_id=request.submission_id,
                reason=request.reason.strip(),
                status="open",
                created_at=now,
            )
            session.add(dispute)
            await session.flush()
            [out] = await self._disputes_out(session, [dispute])
            return out

    async def list_disputes(
        self, user_id: uuid.UUID, challenge_id: uuid.UUID, *, cursor: str | None, limit: int
    ) -> ChallengeDisputePage:
        """Judges see every dispute; members see their own."""
        async with self._sessionmaker() as session:
            row, access = await self._challenge(session, challenge_id, user_id, lock=False)
            conditions: list[Any] = [ChallengeDispute.challenge_id == row.id]
            judge = JUDGE in access.permissions
            if not judge:
                conditions.append(ChallengeDispute.raised_by == user_id)
            filters = {"c": str(row.id), "j": judge}
            if cursor is not None:
                decoded = self._cursors.decode(cursor, scope="challenge-disputes")
                if decoded.get("f") != filters:
                    raise AppError(ErrorCode.INVALID_CURSOR, "The cursor belongs to another query.")
                conditions.append(
                    tuple_(ChallengeDispute.created_at, ChallengeDispute.id)
                    > tuple_(
                        literal(datetime.fromisoformat(decoded["t"])),
                        literal(uuid.UUID(decoded["i"])),
                    )
                )
            rows = list(
                (
                    await session.scalars(
                        select(ChallengeDispute)
                        .where(*conditions)
                        .order_by(ChallengeDispute.created_at, ChallengeDispute.id)
                        .limit(limit + 1)
                    )
                ).all()
            )
            more = len(rows) > limit
            rows = rows[:limit]
            data = await self._disputes_out(session, rows)
        next_cursor = (
            self._cursors.encode(
                {"f": filters, "t": rows[-1].created_at.isoformat(), "i": str(rows[-1].id)},
                scope="challenge-disputes",
            )
            if more and rows
            else None
        )
        return ChallengeDisputePage(data=data, page=PageInfo(next_cursor=next_cursor))

    async def resolve_dispute(
        self,
        user_id: uuid.UUID,
        challenge_id: uuid.UUID,
        dispute_id: uuid.UUID,
        request: ResolveDisputeRequest,
    ) -> ChallengeDisputeOut:
        """A judge closes a dispute (audited); never one they raised themselves (CHAL-016)."""
        async with self._sessionmaker() as session, session.begin():
            row, access = await self._challenge(session, challenge_id, user_id, lock=True)
            self._require_judge(access)
            dispute = await session.get(ChallengeDispute, dispute_id, with_for_update=True)
            if dispute is None or dispute.challenge_id != row.id:
                raise AppError(ErrorCode.NOT_FOUND, "Dispute not found.")
            if dispute.raised_by == user_id:
                raise AppError(ErrorCode.FORBIDDEN, "Another judge has to resolve your dispute.")
            if dispute.status != "open":
                raise AppError(ErrorCode.CONFLICT, "This dispute is already resolved.")
            dispute.status = request.status
            dispute.resolution_note = request.resolution_note.strip()
            dispute.resolved_by = user_id
            dispute.resolved_at = self._clock.now()
            observability.audit(
                session,
                actor_id=user_id,
                actor_type="user",
                action=f"challenge.dispute_{request.status}",
                resource_type="challenge_dispute",
                resource_id=dispute.id,
                metadata={"challenge_id": str(row.id)},
            )
            await session.flush()
            [out] = await self._disputes_out(session, [dispute])
            return out

    # ─────────────────────────────── fulfillment ───────────────────────────────

    async def _fulfillments_out(
        self, session: AsyncSession, rows: Sequence[RewardFulfillment]
    ) -> list[RewardFulfillmentOut]:
        users = await profiles.authors(
            session, [f.recipient_user_id for f in rows if f.recipient_user_id]
        )
        return [
            RewardFulfillmentOut(
                id=f.id,
                challenge_reward_id=f.challenge_reward_id,
                winner_id=f.winner_id,
                recipient=(
                    profiles.user_summary(users[f.recipient_user_id])
                    if f.recipient_user_id in users
                    else None
                ),
                status=f.status,  # type: ignore[arg-type]
                issued_at=f.issued_at,
                delivered_at=f.delivered_at,
                notes=f.notes,
                updated_at=f.updated_at,
            )
            for f in rows
        ]

    async def list_fulfillments(
        self, user_id: uuid.UUID, challenge_id: uuid.UUID, *, cursor: str | None, limit: int
    ) -> RewardFulfillmentPage:
        async with self._sessionmaker() as session:
            row, access = await self._challenge(session, challenge_id, user_id, lock=False)
            self._require_judge(access)
            conditions: list[Any] = [RewardFulfillment.challenge_id == row.id]
            filters = {"c": str(row.id)}
            if cursor is not None:
                decoded = self._cursors.decode(cursor, scope="reward-fulfillments")
                if decoded.get("f") != filters:
                    raise AppError(ErrorCode.INVALID_CURSOR, "The cursor belongs to another query.")
                conditions.append(
                    tuple_(RewardFulfillment.created_at, RewardFulfillment.id)
                    > tuple_(
                        literal(datetime.fromisoformat(decoded["t"])),
                        literal(uuid.UUID(decoded["i"])),
                    )
                )
            rows = list(
                (
                    await session.scalars(
                        select(RewardFulfillment)
                        .where(*conditions)
                        .order_by(RewardFulfillment.created_at, RewardFulfillment.id)
                        .limit(limit + 1)
                    )
                ).all()
            )
            more = len(rows) > limit
            rows = rows[:limit]
            data = await self._fulfillments_out(session, rows)
        next_cursor = (
            self._cursors.encode(
                {"f": filters, "t": rows[-1].created_at.isoformat(), "i": str(rows[-1].id)},
                scope="reward-fulfillments",
            )
            if more and rows
            else None
        )
        return RewardFulfillmentPage(data=data, page=PageInfo(next_cursor=next_cursor))

    async def transition_fulfillment(
        self,
        user_id: uuid.UUID,
        challenge_id: uuid.UUID,
        fulfillment_id: uuid.UUID,
        request: FulfillmentTransitionRequest,
    ) -> RewardFulfillmentOut:
        """Group admins move group- and sponsor-fulfilled rewards through the state machine
        (CHAL-015; audited without the secret). A discount code goes in when it is issued."""
        async with self._sessionmaker() as session, session.begin():
            row, access = await self._challenge(session, challenge_id, user_id, lock=False)
            if MANAGE not in access.role_permissions:
                raise AppError(ErrorCode.FORBIDDEN, "Only group admins handle rewards.")
            fulfillment = await session.get(RewardFulfillment, fulfillment_id, with_for_update=True)
            if fulfillment is None or fulfillment.challenge_id != row.id:
                raise AppError(ErrorCode.NOT_FOUND, "Fulfillment not found.")
            reward = await session.get(ChallengeReward, fulfillment.challenge_reward_id)
            assert reward is not None
            if reward.fulfillment_owner == "platform":
                raise AppError(ErrorCode.FORBIDDEN, "The platform team handles this reward.")
            before, target = fulfillment.status, request.to_status
            if not can_transition(before, target):
                raise AppError(ErrorCode.CONFLICT, f"A reward can't go from {before} to {target}.")
            if request.secret is not None and target != "issued":
                raise _invalid("/secret", "A code goes with issuing the reward only.")
            now = self._clock.now()
            if target == "issued":
                if request.secret is not None:
                    if self._cipher is None:
                        raise AppError(
                            ErrorCode.SERVICE_UNAVAILABLE, "Reward codes can't be stored now."
                        )
                    fulfillment.secret_ciphertext = self._cipher.encrypt(
                        request.secret.strip(), fulfillment_id=fulfillment.id
                    )
                elif (
                    reward.reward_type == "discount_code" and fulfillment.secret_ciphertext is None
                ):
                    raise _invalid("/secret", "Add the discount code to issue it.")
                fulfillment.issued_by = user_id
                fulfillment.issued_at = now
            if target == "delivered":
                fulfillment.delivered_at = now
            fulfillment.status = target
            if request.note:
                fulfillment.notes = request.note.strip()
            fulfillment.updated_at = now
            observability.audit(
                session,
                actor_id=user_id,
                actor_type="user",
                action="challenge.fulfillment_transitioned",
                resource_type="reward_fulfillment",
                resource_id=fulfillment.id,
                metadata={"challenge_id": str(row.id), "from": before, "to": target},
            )
            if target == "issued" and fulfillment.recipient_user_id is not None:
                platform.record_event(
                    session,
                    aggregate_type="challenge",
                    aggregate_id=row.id,
                    event_type=REWARD_ISSUED_EVENT,
                    payload={
                        "challenge_id": str(row.id),
                        "group_id": str(row.group_id),
                        "title": row.title,
                        "recipient_ids": [str(fulfillment.recipient_user_id)],
                    },
                )
            await session.flush()
            [out] = await self._fulfillments_out(session, [fulfillment])
            return out

    async def my_rewards(
        self, user_id: uuid.UUID, *, cursor: str | None, limit: int
    ) -> MyRewardPage:
        """Rewards I won; a discount code shows only to me, once issued (CHAL-015)."""
        async with self._sessionmaker() as session:
            conditions: list[Any] = [RewardFulfillment.recipient_user_id == user_id]
            if cursor is not None:
                decoded = self._cursors.decode(cursor, scope="my-rewards")
                conditions.append(
                    tuple_(RewardFulfillment.created_at, RewardFulfillment.id)
                    < tuple_(
                        literal(datetime.fromisoformat(decoded["t"])),
                        literal(uuid.UUID(decoded["i"])),
                    )
                )
            rows = list(
                (
                    await session.execute(
                        select(RewardFulfillment, ChallengeReward, GroupChallenge)
                        .join(
                            ChallengeReward,
                            ChallengeReward.id == RewardFulfillment.challenge_reward_id,
                        )
                        .join(GroupChallenge, GroupChallenge.id == RewardFulfillment.challenge_id)
                        .where(*conditions)
                        .order_by(RewardFulfillment.created_at.desc(), RewardFulfillment.id.desc())
                        .limit(limit + 1)
                    )
                ).all()
            )
        more = len(rows) > limit
        rows = rows[:limit]
        data = []
        for fulfillment, reward, challenge in rows:
            secret = None
            if (
                fulfillment.status in ("issued", "delivered")
                and fulfillment.secret_ciphertext is not None
                and self._cipher is not None
            ):
                secret = self._cipher.decrypt(
                    fulfillment.secret_ciphertext, fulfillment_id=fulfillment.id
                )
            data.append(
                MyRewardOut(
                    fulfillment_id=fulfillment.id,
                    challenge=RewardChallenge(
                        id=challenge.id, title=challenge.title, group_id=challenge.group_id
                    ),
                    reward=RewardSummary(
                        id=reward.id,
                        reward_type=reward.reward_type,
                        title=reward.title,
                        description=reward.description,
                        sponsor_name=reward.sponsor_name,
                        quantity=reward.quantity,
                        terms_url=reward.terms_url,
                    ),
                    status=fulfillment.status,
                    secret=secret,
                    issued_at=fulfillment.issued_at,
                    delivered_at=fulfillment.delivered_at,
                )
            )
        last = rows[-1][0] if rows else None
        next_cursor = (
            self._cursors.encode(
                {"t": last.created_at.isoformat(), "i": str(last.id)}, scope="my-rewards"
            )
            if more and last is not None
            else None
        )
        return MyRewardPage(data=data, page=PageInfo(next_cursor=next_cursor))

    async def user_badges(self, viewer_id: uuid.UUID, user_id: uuid.UUID) -> UserBadgeList:
        """A user's badges and achievements: non-transferable, hidden across blocks (CHAL-012)."""
        async with self._sessionmaker() as session:
            blocked_by_me, blocked_me = await trust_safety.blocks_of(session, viewer_id)
            if (
                user_id in blocked_by_me
                or user_id in blocked_me
                or user_id not in await identity.active_ids(session, [user_id])
            ):
                raise AppError(ErrorCode.NOT_FOUND, "User not found.")
            rows = (
                await session.execute(
                    select(UserBadge, Badge)
                    .join(Badge, Badge.id == UserBadge.badge_id)
                    .where(UserBadge.user_id == user_id)
                    .order_by(UserBadge.awarded_at.desc(), Badge.key)
                )
            ).all()
            icons = await media.refs(session, [b.icon_media_id for _, b in rows if b.icon_media_id])
        return UserBadgeList(
            data=[
                UserBadgeOut(
                    badge=BadgeSummary(
                        id=badge.id,
                        key=badge.key,
                        name=badge.name,
                        icon=icons.get(badge.icon_media_id) if badge.icon_media_id else None,
                    ),
                    awarded_at=owned.awarded_at,
                    source_type=owned.source_type,
                    source_id=owned.source_id,
                )
                for owned, badge in rows
            ]
        )


def _require_unpublished(row: GroupChallenge) -> None:
    if row.results_published_at is not None or row.status in ("completed", "cancelled"):
        raise AppError(ErrorCode.CONFLICT, "Results are final. Raise a dispute instead.")


async def _winner_people(session: AsyncSession, winner: ChallengeWinner) -> list[uuid.UUID]:
    """Who a winner is: the user, or every active member of the winning team."""
    if winner.team_id is None:
        return [winner.user_id] if winner.user_id else []
    return list(
        await session.scalars(
            select(ChallengeParticipant.user_id).where(
                ChallengeParticipant.team_id == winner.team_id,
                ChallengeParticipant.status == "active",
            )
        )
    )


def reward_detail(reward: ChallengeReward, badge: Badge | None) -> RewardDetail:
    return RewardDetail(
        id=reward.id,
        challenge_id=reward.challenge_id,
        reward_type=reward.reward_type,  # type: ignore[arg-type]
        title=reward.title,
        description=reward.description,
        badge=BadgeSummary(id=badge.id, key=badge.key, name=badge.name) if badge else None,
        sponsor_name=reward.sponsor_name,
        quantity=reward.quantity,
        eligibility_rules=reward.eligibility_rules,
        terms_url=reward.terms_url,
        fulfillment_owner=reward.fulfillment_owner,  # type: ignore[arg-type]
        requires_platform_review=reward.requires_platform_review,
        review_status=reward.review_status,  # type: ignore[arg-type]
        created_at=reward.created_at,
    )


async def review_reward(
    session: AsyncSession, reward_id: uuid.UUID, *, decision: str
) -> RewardDetail:
    """Platform review of a discount or promotional reward before its challenge is published
    (CHAL-014); the admin module audits it in the same transaction."""
    reward = await session.get(ChallengeReward, reward_id, with_for_update=True)
    if reward is None or not reward.requires_platform_review:
        raise AppError(ErrorCode.NOT_FOUND, "Reward not found.")
    challenge = await session.get(GroupChallenge, reward.challenge_id)
    if challenge is None or challenge.status != "draft":
        raise AppError(ErrorCode.CONFLICT, "Only rewards of unpublished challenges are reviewed.")
    reward.review_status = decision
    await session.flush()
    badge = await session.get(Badge, reward.badge_id) if reward.badge_id else None
    return reward_detail(reward, badge)


def _require_open_teams(row: GroupChallenge) -> None:
    if row.solving_mode != "team":
        raise AppError(ErrorCode.CONFLICT, "This challenge is solved individually.")
    if row.status not in TEAMS_OPEN:
        raise AppError(
            ErrorCode.CHALLENGE_NOT_ACTIVE, "Teams can change only until the challenge ends."
        )


async def _captain_team(
    session: AsyncSession,
    participant: ChallengeParticipant | None,
    user_id: uuid.UUID,
    team_id: uuid.UUID | None,
) -> ChallengeTeam:
    """Team mode: only the captain submits, for their own team (CHAL-004)."""
    if participant is None or participant.team_id is None:
        raise AppError(ErrorCode.NOT_TEAM_CAPTAIN, "Join a team first; its captain submits.")
    if team_id is not None and team_id != participant.team_id:
        raise AppError(ErrorCode.NOT_TEAM_CAPTAIN, "You can only submit for your own team.")
    team = await session.get(ChallengeTeam, participant.team_id, with_for_update=True)
    if team is None or team.captain_id != user_id:
        raise AppError(ErrorCode.NOT_TEAM_CAPTAIN, "Only your team captain can submit.")
    return team


def _check_attempt(
    row: GroupChallenge, holder: ChallengeTeam | ChallengeParticipant, now: datetime
) -> None:
    """Attempt limit and cooldown (CHAL-005); per team in team mode."""
    blocked = attempt_block(
        max_attempts=row.max_attempts,
        cooldown_seconds=row.attempt_cooldown_seconds,
        attempts_used=holder.attempts_used,
        last_attempt_at=holder.last_attempt_at,
        now=now,
    )
    if blocked is None:
        return
    _, ready = blocked
    if ready is None:
        raise AppError(ErrorCode.ATTEMPTS_EXHAUSTED, "You have no attempts left.")
    wait = max(1, math.ceil((ready - now).total_seconds()))
    raise AppError(
        ErrorCode.ATTEMPT_COOLDOWN,
        "Wait a moment before trying again.",
        extensions={"retry_after": wait, "next_attempt_at": ready.isoformat()},
        headers={"Retry-After": str(wait)},
    )


async def _sync_winners(session: AsyncSession, row: GroupChallenge, now: datetime) -> None:
    """Make the provisional winners match the policy (CHAL-009, CHAL-010): the first correct
    submissions in submission order, whatever order they were judged in. Confirmed winners stay;
    revoked ones stay out. Runs under the challenge row lock."""
    slots = winner_slots(row.winner_policy, row.max_winners)
    if slots == 0:
        return  # admin_selects: the judges pick

    def recipient(user_id: uuid.UUID | None, team_id: uuid.UUID | None) -> Recipient | None:
        if team_id is not None:
            return ("team", team_id)
        return ("user", user_id) if user_id is not None else None

    winners = list(
        (
            await session.scalars(
                select(ChallengeWinner).where(ChallengeWinner.challenge_id == row.id)
            )
        ).all()
    )
    correct = []
    for submission_id, user_id, team_id in (
        await session.execute(
            select(
                ChallengeSubmission.id,
                ChallengeSubmission.submitted_by,
                ChallengeSubmission.team_id,
            )
            .where(
                ChallengeSubmission.challenge_id == row.id,
                ChallengeSubmission.evaluation_status == "correct",
            )
            .order_by(ChallengeSubmission.submitted_at, ChallengeSubmission.id)
        )
    ).all():
        key = recipient(user_id, team_id)
        if key is not None:
            correct.append((key, submission_id))
    live: dict[Recipient, ChallengeWinner] = {}
    revoked: set[Recipient] = set()
    for winner in winners:
        key = recipient(winner.user_id, winner.team_id)
        if key is None:
            continue
        if winner.status == "revoked":
            revoked.add(key)
        else:
            live[key] = winner
    chosen = pick_winners(
        correct,
        slots=slots,
        confirmed=frozenset(k for k, w in live.items() if w.status == "confirmed"),
        revoked=frozenset(revoked),
    )
    chosen_keys = {key for key, _ in chosen}
    for key, winner in list(live.items()):
        if winner.status == "provisional" and key not in chosen_keys:
            await session.delete(winner)
            del live[key]
    await session.flush()
    for offset, winner in enumerate(live.values()):  # park live ranks clear of the unique index
        winner.rank = 1000 + offset
    await session.flush()
    rank = 0
    for key, submission_id in chosen:
        rank += 1
        existing = live.get(key)
        if existing is None:
            session.add(
                ChallengeWinner(
                    challenge_id=row.id,
                    user_id=key[1] if key[0] == "user" else None,
                    team_id=key[1] if key[0] == "team" else None,
                    submission_id=submission_id,
                    rank=rank,
                    status="provisional",
                    determined_by="system",
                    determined_at=now,
                )
            )
        else:
            existing.rank = rank
            if existing.status == "provisional":
                existing.submission_id = submission_id
    for key, winner in live.items():
        if key not in chosen_keys:  # confirmed, but the answer no longer counts: until revoked
            rank += 1
            winner.rank = rank
    await session.flush()


async def ai_judgement(
    sessionmaker: async_sessionmaker[AsyncSession],
    clock: Clock,
    judge: AnswerJudge | None,
    submission_id: uuid.UUID,
) -> str | None:
    """The AI judge's pass over a pending ``ai_assisted`` answer (CHAL-006, CHAL-007). The model
    call happens outside any transaction; the verdict applies only if no judge decided first."""
    async with sessionmaker() as session:
        submission = await session.get(ChallengeSubmission, submission_id)
        if submission is None or submission.evaluation_status != "pending":
            return None
        row = await session.get(GroupChallenge, submission.challenge_id)
        if row is None or row.validation_method != "ai_assisted" or row.status == "cancelled":
            return None
        accepted = list(
            await session.scalars(
                select(ChallengeAnswer.answer_display)
                .where(ChallengeAnswer.challenge_id == row.id)
                .order_by(ChallengeAnswer.created_at, ChallengeAnswer.id)
            )
        )
        reward_types = list(
            await session.scalars(
                select(ChallengeReward.reward_type).where(ChallengeReward.challenge_id == row.id)
            )
        )
        challenge_id, title, description = row.id, row.title, row.description
        answer, submitter = submission.answer_text, submission.submitted_by
    verdict = (
        await judge(
            user_id=submitter,
            title=title,
            description=description,
            accepted_answers=accepted,
            answer=answer,
        )
        if judge is not None and accepted
        else None
    )
    outcome = ai_outcome(verdict, badge_only=all(t == "badge" for t in reward_types))
    async with sessionmaker() as session, session.begin():
        locked = await session.get(GroupChallenge, challenge_id, with_for_update=True)
        current = await session.get(ChallengeSubmission, submission_id, with_for_update=True)
        if locked is None or current is None or current.evaluation_status != "pending":
            return None  # a judge got there first
        now = clock.now()
        current.evaluation_status = outcome
        if verdict is not None:
            current.evaluator = "ai"
            current.ai_confidence = Decimal(str(round(verdict.confidence, 3)))
            current.ai_rationale = verdict.rationale
        if outcome in ("correct", "incorrect"):
            current.evaluated_at = now
        await session.flush()
        if outcome == "correct":
            await _sync_winners(session, locked, now)
    return outcome


async def advance_lifecycle(session: AsyncSession, *, now: datetime) -> int:
    """Scheduler (CHAL-003): start scheduled challenges, close active ones for judging."""
    moved = 0
    due = (
        await session.scalars(
            select(GroupChallenge)
            .where(
                GroupChallenge.status.in_(("scheduled", "active")),
                ((GroupChallenge.status == "scheduled") & (GroupChallenge.starts_at <= now))
                | ((GroupChallenge.status == "active") & (GroupChallenge.ends_at <= now)),
            )
            .with_for_update(skip_locked=True)
            .limit(200)
        )
    ).all()
    for row in due:
        moved += await _advance(session, row, now)
    return moved


async def _advance(session: AsyncSession, row: GroupChallenge, now: datetime) -> int:
    before = row.status
    row.status = status_at(row.status, row.starts_at, row.ends_at, now)
    if row.status == before:
        return 0
    row.version += 1
    row.updated_at = now
    if before == "scheduled":
        await _record_started(session, row)
    return 1


async def _record_started(session: AsyncSession, row: GroupChallenge) -> None:
    """Members are told when a challenge starts (CHAL-003)."""
    platform.record_event(
        session,
        aggregate_type="challenge",
        aggregate_id=row.id,
        event_type=STARTED_EVENT,
        payload={
            "challenge_id": str(row.id),
            "group_id": str(row.group_id),
            "title": row.title,
            "recipient_ids": [str(m) for m in await groups.member_ids(session, row.group_id)],
        },
    )


async def leave_teams(session: AsyncSession, *, group_id: uuid.UUID, user_id: uuid.UUID) -> int:
    """A member who leaves (or is removed from) the group leaves their teams in its unfinished
    challenges: out of the team thread, and a captain hands over to the longest-standing
    teammate (CHAL-004). Their submissions stay with the team."""
    rows = (
        await session.execute(
            select(ChallengeParticipant, ChallengeTeam)
            .join(ChallengeTeam, ChallengeTeam.id == ChallengeParticipant.team_id)
            .join(GroupChallenge, GroupChallenge.id == ChallengeParticipant.challenge_id)
            .where(
                GroupChallenge.group_id == group_id,
                GroupChallenge.status.not_in(("completed", "cancelled")),
                ChallengeParticipant.user_id == user_id,
            )
            .with_for_update(of=ChallengeTeam)
        )
    ).all()
    for participant, team in rows:
        participant.team_id = None
        if team.conversation_id is not None:
            await messaging.remove_group_member(session, team.conversation_id, user_id)
        if team.captain_id == user_id:
            team.captain_id = await session.scalar(
                select(ChallengeParticipant.user_id)
                .where(
                    ChallengeParticipant.team_id == team.id,
                    ChallengeParticipant.status == "active",
                    ChallengeParticipant.user_id != user_id,
                )
                .order_by(ChallengeParticipant.joined_at, ChallengeParticipant.user_id)
                .limit(1)
            )
    await session.flush()
    return len(rows)


def subscribe(router: platform.EventRouter) -> None:
    for event in MEMBER_GONE_EVENTS:
        router.subscribe(event, queue="default", kind=MEMBER_GONE_JOB)


def make_handlers(
    sessionmaker: async_sessionmaker[AsyncSession],
    clock: Clock,
    *,
    judge: AnswerJudge | None = None,
) -> dict[str, platform.JobHandler]:
    async def lifecycle(job: platform.Job) -> None:
        async with sessionmaker() as session, session.begin():
            await advance_lifecycle(session, now=clock.now())

    async def member_gone(job: platform.Job) -> None:
        data = job.payload.get("data") or {}
        async with sessionmaker() as session, session.begin():
            await leave_teams(
                session,
                group_id=uuid.UUID(str(data["group_id"])),
                user_id=uuid.UUID(str(data["user_id"])),
            )

    async def judge_answer(job: platform.Job) -> None:
        await ai_judgement(sessionmaker, clock, judge, uuid.UUID(str(job.payload["submission_id"])))

    return {
        LIFECYCLE_JOB: lifecycle,
        MEMBER_GONE_JOB: member_gone,
        AI_JUDGE_JOB: judge_answer,
    }
