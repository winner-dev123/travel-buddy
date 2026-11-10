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
* Submissions (CHAL-005, CHAL-009, CHAL-010) are idempotent and append-only. Each one locks the
  challenge row, so submissions to a challenge are serialized and first-correct order is commit
  order. Attempts and the cooldown are checked under that lock. A normalized exact match is
  judged at once; a correct answer becomes a provisional winner while the winner policy has
  slots left. Members get no feedback beyond the evaluation status.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.pagination import CursorCodec, PageInfo
from app.core.security.principal import Principal
from app.core.time import Clock
from app.modules.challenges.domain import (
    EDITABLE,
    REVIEWED_REWARDS,
    Normalization,
    RewardInput,
    attempt_block,
    first_evaluation,
    next_attempt_at,
    normalize,
    prohibited_prize,
    reward_problems,
    status_at,
    winner_slots,
)
from app.modules.challenges.models import (
    Badge,
    ChallengeAnswer,
    ChallengeHint,
    ChallengeParticipant,
    ChallengeReward,
    ChallengeSubmission,
    ChallengeWinner,
    GroupChallenge,
)
from app.modules.challenges.schemas import (
    AnswerNormalization,
    BadgeSummary,
    ChallengeHintOut,
    ChallengeManagerView,
    ChallengeOut,
    ChallengePage,
    ChallengeResults,
    ChallengeSubmissionOut,
    ChallengeSubmissionPage,
    ChallengeWinnerOut,
    CreateChallengeRequest,
    HintList,
    ManagedHint,
    Participation,
    RewardDetail,
    RewardSummary,
    SubmissionResult,
    SubmitAnswerRequest,
    UpdateChallengeRequest,
)
from app.modules.groups import service as groups
from app.modules.media import service as media
from app.modules.platform import service as platform
from app.modules.profiles import service as profiles

CREATE_ROUTE = "POST /v1/groups/{id}/challenges"
SUBMIT_ROUTE = "POST /v1/challenges/{id}/submissions"
MANAGE = "challenges.manage"
JUDGE = "challenges.judge"
STARTED_EVENT = "challenge.started"
CANCELLED_EVENT = "challenge.cancelled"
LIFECYCLE_JOB = "challenges.lifecycle"
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
    ) -> None:
        self._sessionmaker = sessionmaker
        self._clock = clock
        self._cursors = cursors

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
            participation = Participation(
                attempts_used=participant.attempts_used,
                attempts_remaining=max(0, row.max_attempts - participant.attempts_used),
                next_attempt_at=next_attempt_at(
                    participant.last_attempt_at, row.attempt_cooldown_seconds, now
                ),
                team_id=participant.team_id,
                is_captain=False,
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
                    RewardDetail(
                        id=r.id,
                        challenge_id=r.challenge_id,
                        reward_type=r.reward_type,
                        title=r.title,
                        description=r.description,
                        badge=(
                            BadgeSummary(
                                id=badges[r.badge_id].id,
                                key=badges[r.badge_id].key,
                                name=badges[r.badge_id].name,
                            )
                            if r.badge_id in badges
                            else None
                        ),
                        sponsor_name=r.sponsor_name,
                        quantity=r.quantity,
                        eligibility_rules=r.eligibility_rules,
                        terms_url=r.terms_url,
                        fulfillment_owner=r.fulfillment_owner,
                        requires_platform_review=r.requires_platform_review,
                        review_status=r.review_status,
                        created_at=r.created_at,
                    )
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
            row, _ = await self._challenge(session, challenge_id, user_id, lock=True)
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
            if row.solving_mode == "team":
                raise AppError(ErrorCode.NOT_TEAM_CAPTAIN, "Only a team captain can submit.")
            normalized = normalize(request.answer, Normalization.from_json(row.normalization))
            if not normalized:
                raise _invalid("/answer", "Type an answer.")
            participant = await session.get(
                ChallengeParticipant, (row.id, user_id), with_for_update=True
            )
            if participant is None:
                participant = ChallengeParticipant(
                    challenge_id=row.id,
                    user_id=user_id,
                    joined_at=now,
                    attempts_used=0,
                    status="active",
                )
                session.add(participant)
            elif participant.status != "active":
                raise AppError(ErrorCode.FORBIDDEN, "You can't take part in this challenge.")
            solved = await session.scalar(
                select(ChallengeSubmission.id)
                .where(
                    ChallengeSubmission.challenge_id == row.id,
                    ChallengeSubmission.submitted_by == user_id,
                    ChallengeSubmission.evaluation_status == "correct",
                )
                .limit(1)
            )
            if solved is not None:
                raise AppError(ErrorCode.CONFLICT, "You already solved this challenge.")
            _check_attempt(row, participant, now)
            accepted = set(
                await session.scalars(
                    select(ChallengeAnswer.answer_normalized).where(
                        ChallengeAnswer.challenge_id == row.id
                    )
                )
            )
            evaluation, evaluator = first_evaluation(row.validation_method, normalized in accepted)
            participant.attempts_used += 1
            participant.last_attempt_at = now
            submission = ChallengeSubmission(
                challenge_id=row.id,
                submitted_by=user_id,
                attempt_no=participant.attempts_used,
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
            won = evaluation == "correct" and await _award(session, row, submission, now)
            remaining = max(0, row.max_attempts - participant.attempts_used)
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
                conditions.append(ChallengeSubmission.submitted_by == user_id)
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
            users = await profiles.authors(
                session, [r.submitted_by for r in rows if r.submitted_by]
            )
        data = [
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
        next_cursor = (
            self._cursors.encode(
                {"f": filters, "t": rows[-1].submitted_at.isoformat(), "i": str(rows[-1].id)},
                scope="challenge-submissions",
            )
            if more and rows
            else None
        )
        return ChallengeSubmissionPage(data=data, page=PageInfo(next_cursor=next_cursor))

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
            users = await profiles.authors(session, [w.user_id for w in winners if w.user_id])
        return ChallengeResults(
            challenge_id=row.id,
            status=row.status,  # type: ignore[arg-type]
            published=published,
            results_published_at=row.results_published_at,
            participant_count=int(participants or 0),
            winners=[
                ChallengeWinnerOut(
                    id=w.id,
                    rank=w.rank,
                    user=profiles.user_summary(users[w.user_id]) if w.user_id in users else None,
                    team=None,
                    status=w.status,  # type: ignore[arg-type]
                    determined_by=w.determined_by,  # type: ignore[arg-type]
                    determined_at=w.determined_at,
                )
                for w in winners
            ],
        )


def _check_attempt(row: GroupChallenge, participant: ChallengeParticipant, now: datetime) -> None:
    """Attempt limit and cooldown (CHAL-005)."""
    blocked = attempt_block(
        max_attempts=row.max_attempts,
        cooldown_seconds=row.attempt_cooldown_seconds,
        attempts_used=participant.attempts_used,
        last_attempt_at=participant.last_attempt_at,
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


async def _award(
    session: AsyncSession, row: GroupChallenge, submission: ChallengeSubmission, now: datetime
) -> bool:
    """A correct answer becomes a provisional winner while the policy has slots (CHAL-010).
    Runs under the challenge row lock, so ranks follow submission order."""
    slots = winner_slots(row.winner_policy, row.max_winners)
    if slots == 0:
        return False
    live = ChallengeWinner.status != "revoked"
    taken = await session.scalar(
        select(func.count())
        .select_from(ChallengeWinner)
        .where(ChallengeWinner.challenge_id == row.id, live)
    )
    if slots is not None and int(taken or 0) >= slots:
        return False
    top = await session.scalar(
        select(func.coalesce(func.max(ChallengeWinner.rank), 0)).where(
            ChallengeWinner.challenge_id == row.id, live
        )
    )
    session.add(
        ChallengeWinner(
            challenge_id=row.id,
            user_id=None if submission.team_id else submission.submitted_by,
            team_id=submission.team_id,
            submission_id=submission.id,
            rank=int(top or 0) + 1,
            status="provisional",
            determined_by="system",
            determined_at=now,
        )
    )
    await session.flush()
    return True


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


def make_handlers(
    sessionmaker: async_sessionmaker[AsyncSession], clock: Clock
) -> dict[str, platform.JobHandler]:
    async def lifecycle(job: platform.Job) -> None:
        async with sessionmaker() as session, session.begin():
            await advance_lifecycle(session, now=clock.now())

    return {LIFECYCLE_JOB: lifecycle}
