"""AI generations (BL-4.02; AI-001, AI-009) and itinerary generation (AI-002..004, AI-007, AI-008).

Lifecycle:

1. ``POST`` validates the request, checks the circuit breakers and the user's monthly quota, stores
   a ``pending`` generation and records ``ai.generation_requested`` (all in one transaction).
2. The event's job builds the typed context, calls the provider outside any transaction, validates
   the output (schema, then semantic checks, one repair retry) and stores either the validated
   proposal or a typed error, together with the call's telemetry. It then records
   ``ai.generation_completed``, which becomes an ``ai_generation_ready`` notification.
3. The owner polls ``GET /v1/ai/generations/{id}`` (or waits for the notification).

Cost controls (AI-009): quotas count this month's ``pending`` and ``succeeded`` generations (failed
ones are free), a global daily spend budget and a provider breaker (N failures in a row within the
cooldown) refuse new work with ``503 ai_unavailable``. Both breakers read ``ai_generations``, so
every API instance and worker sees the same state.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import Any, Literal

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode, FieldError, build_problem
from app.core.request_context import current_request_id
from app.core.security.principal import Principal
from app.core.time import Clock
from app.modules.ai_assistant import judging, translation
from app.modules.ai_assistant.domain import (
    DRAFT_SCHEMA,
    MAX_DAYS,
    PROMPT_VERSION,
    REPLAN_PROMPT_VERSION,
    Candidate,
    CurrentItem,
    ItineraryContext,
    ItineraryDraft,
    Replan,
    build_prompt,
    build_proposal,
    repair_feedback,
    schema_errors,
    semantic_errors,
)
from app.modules.ai_assistant.judging import AnswerVerdict
from app.modules.ai_assistant.models import AIGeneration, PostTranslation
from app.modules.ai_assistant.provider import (
    AIProvider,
    AITask,
    ProviderError,
    TaskConfig,
    Usage,
    cost_micros,
)
from app.modules.ai_assistant.schemas import (
    AIGenerationOut,
    GenerateItineraryRequest,
    ItineraryProposal,
    ReplanDay,
    ReplanItem,
    ReplanParams,
    ReplanTripRequest,
    TranslationOut,
)
from app.modules.billing import service as billing
from app.modules.billing.schemas import QuotaStatusOut
from app.modules.destinations import service as destinations
from app.modules.destinations.schemas import DestinationSummary
from app.modules.identity import service as identity
from app.modules.platform import service as platform
from app.modules.social import service as social
from app.modules.trips import service as trips

GENERATE_ROUTE = "POST /v1/ai/itineraries/generate"
REPLAN_ROUTE = "POST /v1/ai/trips/{id}/replan"
REQUESTED_EVENT = "ai.generation_requested"
COMPLETED_EVENT = "ai.generation_completed"
JOB_KIND = "ai.generate"
STALE_AFTER = timedelta(minutes=30)
COUNTED = ("pending", "succeeded")
QUOTAS: Mapping[AITask, billing.Quota] = {
    AITask.ITINERARY_GENERATE: billing.Quota.AI_ITINERARY_GENERATIONS,
    AITask.TRIP_REPLAN: billing.Quota.AI_TRIP_REPLANS,
}
_LOCK_NAMESPACE = 4202  # pg_advisory_xact_lock(namespace, key): per-user quota serialization
_FAILURES: Mapping[str, tuple[ErrorCode, str]] = {
    "validation_failed": (
        ErrorCode.AI_OUTPUT_INVALID,
        "The assistant couldn't produce a valid plan. Try again, maybe with fewer constraints.",
    ),
    "refused": (
        ErrorCode.AI_OUTPUT_INVALID,
        "The assistant couldn't plan this trip. Try different preferences.",
    ),
    "provider_error": (
        ErrorCode.AI_UNAVAILABLE,
        "The travel assistant isn't available right now. Try again later.",
    ),
    "unavailable": (
        ErrorCode.AI_UNAVAILABLE,
        "The travel assistant isn't available right now. Try again later.",
    ),
}
_TRANSLATION_FAILURES: Mapping[str, tuple[ErrorCode, str]] = {
    "validation_failed": (ErrorCode.AI_OUTPUT_INVALID, "The translation didn't work. Try again."),
    "refused": (ErrorCode.AI_OUTPUT_INVALID, "This post can't be translated."),
    "provider_error": (
        ErrorCode.AI_UNAVAILABLE,
        "Translation isn't available right now. Try again later.",
    ),
}
_JUDGE_FAILURES: Mapping[str, ErrorCode] = {
    "validation_failed": ErrorCode.AI_OUTPUT_INVALID,
    "refused": ErrorCode.AI_OUTPUT_INVALID,
    "provider_error": ErrorCode.AI_UNAVAILABLE,
}
_FAILURE_STATUS: Mapping[ErrorCode, int] = {
    ErrorCode.AI_OUTPUT_INVALID: HTTPStatus.BAD_GATEWAY,
    ErrorCode.AI_UNAVAILABLE: HTTPStatus.SERVICE_UNAVAILABLE,
}


@dataclass(frozen=True, slots=True)
class SpendPolicy:
    daily_budget_micros: int
    breaker_failures: int
    breaker_cooldown: timedelta


def _invalid(field_path: str, message: str) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_FAILED,
        message,
        errors=[FieldError(field=field_path, code="invalid", message=message)],
    )


def _not_found() -> AppError:
    return AppError(ErrorCode.NOT_FOUND, "Generation not found.")


def _month_start(at: datetime) -> datetime:
    at = at.astimezone(UTC)
    return datetime(at.year, at.month, 1, tzinfo=UTC)


def _day_start(at: datetime) -> datetime:
    at = at.astimezone(UTC)
    return datetime(at.year, at.month, at.day, tzinfo=UTC)


async def _used(session: AsyncSession, user_id: uuid.UUID, task: AITask, at: datetime) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(AIGeneration)
        .where(
            AIGeneration.user_id == user_id,
            AIGeneration.feature == task.value,
            AIGeneration.status.in_(COUNTED),
            AIGeneration.created_at >= _month_start(at),
        )
    )
    return int(count or 0)


async def quota_status(
    session: AsyncSession, user_id: uuid.UUID, task: AITask, at: datetime
) -> QuotaStatusOut:
    snap = await billing.snapshot(session, user_id, at=at)
    status = snap.quota(QUOTAS[task], used=await _used(session, user_id, task, at))
    return QuotaStatusOut(limit=status.limit, used=status.used, resets_at=status.resets_at)


async def quota_usage(
    session: AsyncSession, user_id: uuid.UUID, at: datetime
) -> dict[billing.Quota, int]:
    """This month's AI usage per quota (read by entitlements; injected by the composition root)."""
    return {quota: await _used(session, user_id, task, at) for task, quota in QUOTAS.items()}


async def breaker_open(
    session: AsyncSession, policy: SpendPolicy, now: datetime
) -> Literal["budget", "provider"] | None:
    """Why new AI work must not start right now, or ``None``."""
    spent = await session.scalar(
        select(func.coalesce(func.sum(AIGeneration.cost_micros), 0)).where(
            AIGeneration.created_at >= _day_start(now)
        )
    )
    if int(spent or 0) >= policy.daily_budget_micros:
        return "budget"
    recent = (
        await session.scalars(
            select(AIGeneration.status)
            .where(
                AIGeneration.completed_at >= now - policy.breaker_cooldown,
                AIGeneration.status.in_(
                    ("succeeded", "validation_failed", "refused", "provider_error")
                ),
            )
            .order_by(AIGeneration.completed_at.desc())
            .limit(policy.breaker_failures)
        )
    ).all()
    if len(recent) == policy.breaker_failures and all(s == "provider_error" for s in recent):
        return "provider"
    return None


async def proposal_for(
    session: AsyncSession, user_id: uuid.UUID, generation_id: uuid.UUID
) -> dict[str, Any] | None:
    """The validated proposal of the user's own succeeded generation (``apply-itinerary``)."""
    row = await session.get(AIGeneration, generation_id)
    if row is None or row.user_id != user_id or row.status != "succeeded":
        return None
    return row.result


@dataclass
class _Run:
    """What the provider calls cost, kept even when a later attempt fails."""

    model: str
    usage: Usage = field(default_factory=Usage)
    attempts: int = 0
    provider_request_id: str | None = None
    errors: list[str] = field(default_factory=list)


class AIService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        clock: Clock,
        provider: AIProvider | None,
        tasks: Mapping[AITask, TaskConfig],
        policy: SpendPolicy,
        problem_base_url: str,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._clock = clock
        self._provider = provider
        self._tasks = dict(tasks)
        self._policy = policy
        self._problem_base_url = problem_base_url

    # ─────────────────────────────── output ───────────────────────────────

    def _out(self, row: AIGeneration, quota: QuotaStatusOut) -> AIGenerationOut:
        status: Literal["pending", "succeeded", "failed"]
        error = None
        if row.status == "pending":
            status = "pending"
        elif row.status == "succeeded":
            status = "succeeded"
        else:
            status = "failed"
            code, detail = _FAILURES.get(row.status, _FAILURES["provider_error"])
            http_status = _FAILURE_STATUS[code]
            error = build_problem(
                type_base_url=self._problem_base_url,
                code=code,
                status=http_status,
                title=HTTPStatus(http_status).phrase,
                detail=detail,
            )
        return AIGenerationOut.model_validate(
            {
                "id": row.id,
                "feature": row.feature,
                "status": status,
                "created_at": row.created_at,
                "completed_at": row.completed_at,
                "result": row.result if status == "succeeded" else None,
                "error": error,
                "quota": quota,
            }
        )

    # ─────────────────────────────── requests ───────────────────────────────

    async def _guard(self, session: AsyncSession, now: datetime) -> AIProvider:
        if self._provider is None:
            raise AppError(
                ErrorCode.AI_UNAVAILABLE, "The travel assistant isn't available right now."
            )
        if await breaker_open(session, self._policy, now) is not None:
            raise AppError(
                ErrorCode.AI_UNAVAILABLE,
                "The travel assistant is busy. Try again in a few minutes.",
                headers={"Retry-After": str(int(self._policy.breaker_cooldown.total_seconds()))},
            )
        return self._provider

    async def generate_itinerary(
        self,
        principal: Principal,
        request: GenerateItineraryRequest,
        *,
        idempotency_key: uuid.UUID,
        locale: str,
    ) -> AIGenerationOut:
        if (request.end_date - request.start_date).days + 1 > MAX_DAYS:
            raise _invalid("/end_date", f"Itineraries cover up to {MAX_DAYS} days.")
        task = AITask.ITINERARY_GENERATE
        user_id = principal.user_id
        now = self._clock.now()
        try:
            async with self._sessionmaker() as session, session.begin():
                replay = await platform.idempotency.claim(
                    session,
                    user_id=user_id,
                    key=idempotency_key,
                    route=GENERATE_ROUTE,
                    payload={**request.model_dump(mode="json"), "locale": locale},
                )
                if replay is not None:
                    return AIGenerationOut.model_validate(replay.body)
                if not await destinations.is_active(session, request.destination_id):
                    raise _invalid("/destination_id", "Pick a destination from the list.")
                return await self._accept(
                    session,
                    user_id=user_id,
                    task=task,
                    prompt_version=PROMPT_VERSION,
                    params=request.model_dump(mode="json"),
                    locale=locale,
                    idempotency_key=idempotency_key,
                    now=now,
                )
        except AppError as exc:
            if exc.code is ErrorCode.QUOTA_EXCEEDED:
                await self._record_denied(user_id, task, locale, now)
            raise

    async def replan_trip(
        self,
        principal: Principal,
        trip_id: uuid.UUID,
        request: ReplanTripRequest,
        *,
        idempotency_key: uuid.UUID,
        locale: str,
    ) -> AIGenerationOut:
        """Propose changes to an existing trip (AI-005, premium). Nothing changes until the client
        applies the proposal with ``POST /v1/trips/{id}/apply-itinerary``."""
        task = AITask.TRIP_REPLAN
        user_id = principal.user_id
        now = self._clock.now()
        try:
            async with self._sessionmaker() as session, session.begin():
                replay = await platform.idempotency.claim(
                    session,
                    user_id=user_id,
                    key=idempotency_key,
                    route=REPLAN_ROUTE,
                    payload={"trip_id": str(trip_id), **request.model_dump(mode="json")},
                )
                if replay is not None:
                    return AIGenerationOut.model_validate(replay.body)
                snapshot = await trips.replan_snapshot(session, trip_id, user_id)
                feature = billing.Feature.AI_TRIP_REPLAN
                if not await billing.has(session, user_id, feature, at=now):
                    raise AppError(
                        ErrorCode.ENTITLEMENT_REQUIRED,
                        "Replanning trips is a premium feature.",
                        extensions={"entitlement": feature.value},
                    )
                if snapshot.version != request.base_version:
                    raise AppError(
                        ErrorCode.CONFLICT,
                        "The trip changed since you opened it. Reload it and try again.",
                    )
                if snapshot.destination_id is None:
                    raise _invalid("/trip", "Add a destination to the trip first.")
                existing = [day.day_index for day in snapshot.days]
                indexes = sorted(set(request.day_indexes or existing))
                if not indexes or any(index not in existing for index in indexes):
                    raise _invalid("/day_indexes", "Pick days of this trip.")
                if len(indexes) > MAX_DAYS:
                    raise _invalid("/day_indexes", f"Replan up to {MAX_DAYS} days at a time.")
                item_ids = {item.id for day in snapshot.days for item in day.items}
                keep = request.constraints.keep_item_ids
                if any(item_id not in item_ids for item_id in keep):
                    raise _invalid("/constraints/keep_item_ids", "Keep items of this trip only.")
                params = ReplanParams(
                    trip_id=snapshot.id,
                    destination_id=snapshot.destination_id,
                    start_date=snapshot.start_date,
                    end_date=snapshot.end_date,
                    instruction=request.instruction.strip(),
                    day_indexes=indexes,
                    pace=request.constraints.pace or "moderate",
                    avoid_categories=list(request.constraints.avoid_categories),
                    keep_item_ids=list(keep),
                    current=[
                        ReplanDay(
                            day_index=day.day_index,
                            items=[
                                ReplanItem(
                                    id=item.id,
                                    title=item.title,
                                    kind=item.kind,
                                    start_time=item.start_time,
                                    duration_minutes=item.duration_minutes,
                                    place_id=item.place_id,
                                )
                                for item in day.items
                            ],
                        )
                        for day in snapshot.days
                    ],
                )
                return await self._accept(
                    session,
                    user_id=user_id,
                    task=task,
                    prompt_version=REPLAN_PROMPT_VERSION,
                    params=params.model_dump(mode="json"),
                    locale=locale,
                    idempotency_key=idempotency_key,
                    now=now,
                )
        except AppError as exc:
            if exc.code is ErrorCode.QUOTA_EXCEEDED:
                await self._record_denied(user_id, task, locale, now)
            raise

    async def _accept(
        self,
        session: AsyncSession,
        *,
        user_id: uuid.UUID,
        task: AITask,
        prompt_version: str,
        params: dict[str, Any],
        locale: str,
        idempotency_key: uuid.UUID,
        now: datetime,
    ) -> AIGenerationOut:
        """Breakers, the user's monthly quota (serialized per user), then a ``pending``
        generation with its request event; completes the idempotency key."""
        provider = await self._guard(session, now)
        await session.execute(
            select(func.pg_advisory_xact_lock(_LOCK_NAMESPACE, _lock_key(user_id)))
        )
        quota = await quota_status(session, user_id, task, now)
        if quota.used >= quota.limit:
            raise AppError(
                ErrorCode.QUOTA_EXCEEDED,
                "You've used this month's AI plans.",
                status=HTTPStatus.CONFLICT,
                extensions={"feature_key": QUOTAS[task].value},
            )
        row = AIGeneration(
            user_id=user_id,
            feature=task.value,
            provider=provider.name,
            model=self._tasks[task].model,
            prompt_version=prompt_version,
            status="pending",
            locale=locale,
            params=params,
            validation_errors=[],
            request_id=current_request_id(),
            created_at=now,
        )
        session.add(row)
        await session.flush()
        platform.record_event(
            session,
            aggregate_type="ai_generation",
            aggregate_id=row.id,
            event_type=REQUESTED_EVENT,
            payload={"generation_id": str(row.id)},
        )
        out = self._out(row, quota.model_copy(update={"used": quota.used + 1}))
        await platform.idempotency.complete(
            session,
            user_id=user_id,
            key=idempotency_key,
            status=HTTPStatus.ACCEPTED,
            body=out.model_dump(mode="json"),
        )
        return out

    async def _record_denied(
        self, user_id: uuid.UUID, task: AITask, locale: str, now: datetime
    ) -> None:
        """Telemetry for a request the quota refused (its own transaction: the request's rolled
        back)."""
        config = self._tasks[task]
        async with self._sessionmaker() as session, session.begin():
            session.add(
                AIGeneration(
                    user_id=user_id,
                    feature=task.value,
                    provider=self._provider.name if self._provider else "none",
                    model=config.model,
                    prompt_version=PROMPT_VERSION,
                    status="quota_exceeded",
                    locale=locale,
                    validation_errors=[],
                    request_id=current_request_id(),
                    created_at=now,
                    completed_at=now,
                )
            )

    async def get(self, user_id: uuid.UUID, generation_id: uuid.UUID) -> AIGenerationOut:
        now = self._clock.now()
        async with self._sessionmaker() as session, session.begin():
            row = await session.get(AIGeneration, generation_id, with_for_update=True)
            if row is None or row.user_id != user_id or row.status == "quota_exceeded":
                raise _not_found()
            if row.status == "pending" and row.created_at < now - STALE_AFTER:
                # The job died for good (a crashed worker exhausted its retries).
                self._close(row, "provider_error", now)
            return self._out(row, await quota_status(session, user_id, AITask(row.feature), now))

    # ─────────────────────────────── post translation ───────────────────────────────

    async def translate_post(
        self, viewer_id: uuid.UUID, post_id: uuid.UUID, target: str
    ) -> TranslationOut:
        """A labelled machine translation of a post the viewer can see (POST-010, I18N-006).
        Needs the viewer's ``post_translation`` consent; the cached translation is reused while
        the post's text is unchanged."""
        now = self._clock.now()
        async with self._sessionmaker() as session:
            post = await social.visible_post(session, post_id, viewer_id)
            if not await identity.consent_granted(session, viewer_id, "post_translation"):
                raise AppError(
                    ErrorCode.CONSENT_REQUIRED,
                    "Turn on post translation in your settings first.",
                    extensions={"consent_type": "post_translation"},
                )
            text, source = post.body.strip(), post.language
            if not text:
                raise _invalid("/target", "This post has no text to translate.")
            if translation.same_language(source, target):
                raise _invalid("/target", "This post is already in that language.")
            digest = translation.body_hash(post.body)
            cached = await session.get(PostTranslation, (post_id, target))
            if cached is not None and cached.body_hash == digest:
                return _translation(post_id, source, target, cached.text, cached.model)
            provider = await self._guard(session, now)

        config = self._tasks[AITask.POST_TRANSLATE]
        run = _Run(model=config.model)
        status, result = "provider_error", None
        started = time.monotonic()
        try:
            completion = await provider.complete(
                task=AITask.POST_TRANSLATE,
                config=config,
                prompt=translation.build_prompt(
                    text, source_language=source, target_language=target
                ),
                schema=translation.SCHEMA,
            )
            run.attempts, run.usage, run.model = 1, completion.usage, completion.model
            run.provider_request_id = completion.provider_request_id
            status = "refused" if completion.refused else "validation_failed"
            if not completion.refused:
                try:
                    draft = translation.TranslationDraft.model_validate_json(completion.text or "")
                except ValidationError:
                    pass
                else:
                    if translation.plausible(draft.text, text):
                        status, result = "succeeded", draft.text
        except ProviderError:
            status = "provider_error"
        latency_ms = int((time.monotonic() - started) * 1000)

        finished = self._clock.now()
        async with self._sessionmaker() as session, session.begin():
            session.add(
                AIGeneration(
                    user_id=viewer_id,
                    feature=AITask.POST_TRANSLATE.value,
                    provider=provider.name,
                    model=run.model,
                    prompt_version=translation.PROMPT_VERSION,
                    status=status,
                    locale=target,
                    input_tokens=run.usage.input_tokens,
                    output_tokens=run.usage.output_tokens,
                    cache_read_tokens=run.usage.cache_read_tokens,
                    cache_write_tokens=run.usage.cache_write_tokens,
                    cost_micros=cost_micros(run.model, run.usage),
                    latency_ms=latency_ms,
                    attempts=run.attempts,
                    error_code=(
                        None if status == "succeeded" else _TRANSLATION_FAILURES[status][0].value
                    ),
                    validation_errors=[],
                    request_id=current_request_id(),
                    provider_request_id=run.provider_request_id,
                    created_at=now,
                    completed_at=finished,
                )
            )
            if result is not None:
                fields = {
                    "source_language": source,
                    "body_hash": digest,
                    "text": result,
                    "model": run.model,
                    "created_at": finished,
                }
                await session.execute(
                    insert(PostTranslation)
                    .values(post_id=post_id, target_language=target, **fields)
                    .on_conflict_do_update(
                        index_elements=[PostTranslation.post_id, PostTranslation.target_language],
                        set_=fields,
                    )
                )
        if result is None:
            code, detail = _TRANSLATION_FAILURES[status]
            raise AppError(code, detail)
        return _translation(post_id, source, target, result, run.model)

    async def judge_answer(
        self,
        *,
        user_id: uuid.UUID | None,
        title: str,
        description: str,
        accepted_answers: Sequence[str],
        answer: str,
    ) -> AnswerVerdict | None:
        """An advisory verdict on a riddle answer (CHAL-006), or ``None`` when the model is
        unavailable, refuses or answers outside the schema; the caller then routes the answer to
        a human. The answer is quoted data under a strict schema (T-CHAL-05)."""
        now = self._clock.now()
        async with self._sessionmaker() as session:
            try:
                provider = await self._guard(session, now)
            except AppError:
                return None
        config = self._tasks[AITask.CHALLENGE_JUDGE]
        run = _Run(model=config.model)
        status, verdict = "provider_error", None
        started = time.monotonic()
        try:
            completion = await provider.complete(
                task=AITask.CHALLENGE_JUDGE,
                config=config,
                prompt=judging.build_prompt(
                    title=title,
                    description=description,
                    accepted_answers=accepted_answers,
                    answer=answer,
                ),
                schema=judging.SCHEMA,
            )
            run.attempts, run.usage, run.model = 1, completion.usage, completion.model
            run.provider_request_id = completion.provider_request_id
            status = "refused" if completion.refused else "validation_failed"
            if not completion.refused:
                try:
                    draft = judging.VerdictDraft.model_validate_json(completion.text or "")
                except ValidationError:
                    pass
                else:
                    status = "succeeded"
                    verdict = AnswerVerdict(
                        matches=draft.matches,
                        confidence=draft.confidence,
                        rationale=draft.rationale,
                    )
        except ProviderError:
            status = "provider_error"
        latency_ms = int((time.monotonic() - started) * 1000)
        async with self._sessionmaker() as session, session.begin():
            session.add(
                AIGeneration(
                    user_id=user_id,
                    feature=AITask.CHALLENGE_JUDGE.value,
                    provider=provider.name,
                    model=run.model,
                    prompt_version=judging.PROMPT_VERSION,
                    status=status,
                    input_tokens=run.usage.input_tokens,
                    output_tokens=run.usage.output_tokens,
                    cache_read_tokens=run.usage.cache_read_tokens,
                    cache_write_tokens=run.usage.cache_write_tokens,
                    cost_micros=cost_micros(run.model, run.usage),
                    latency_ms=latency_ms,
                    attempts=run.attempts,
                    error_code=None if verdict else _JUDGE_FAILURES[status].value,
                    validation_errors=[],
                    request_id=current_request_id(),
                    provider_request_id=run.provider_request_id,
                    created_at=now,
                    completed_at=self._clock.now(),
                )
            )
        return verdict

    # ─────────────────────────────── the job ───────────────────────────────

    def _close(self, row: AIGeneration, status: str, now: datetime) -> None:
        row.status = status
        row.completed_at = now
        row.params = None  # the request is not kept once answered (AI-008)
        if status != "succeeded":
            row.error_code = _FAILURES[status][0].value

    def _completed(self, session: AsyncSession, row: AIGeneration) -> None:
        if row.user_id is None:
            return
        platform.record_event(
            session,
            aggregate_type="ai_generation",
            aggregate_id=row.id,
            event_type=COMPLETED_EVENT,
            payload={
                "generation_id": str(row.id),
                "user_id": str(row.user_id),
                "feature": row.feature,
                "status": "succeeded" if row.status == "succeeded" else "failed",
            },
        )

    async def run(self, generation_id: uuid.UUID) -> None:
        """Answer one pending generation. Idempotent: anything but ``pending`` is left alone."""
        now = self._clock.now()
        async with self._sessionmaker() as session, session.begin():
            row = await session.get(AIGeneration, generation_id, with_for_update=True)
            if row is None or row.status != "pending" or row.params is None:
                return
            provider = self._provider
            if provider is None or await breaker_open(session, self._policy, now) is not None:
                self._close(row, "unavailable", now)
                self._completed(session, row)
                return
            task = AITask(row.feature)
            config = self._tasks[task]
            built = await self._context(session, row)
            if built is None:  # the destination was retired meanwhile
                self._close(row, "unavailable", now)
                self._completed(session, row)
                return
            context, summary, destination_id = built

        run = _Run(model=config.model)
        failure: ProviderError | None = None
        draft: ItineraryDraft | None = None
        status = "provider_error"
        started = time.monotonic()
        try:
            status, draft = await self._generate(provider, task, config, context, run)
        except ProviderError as exc:
            failure = exc
        latency_ms = int((time.monotonic() - started) * 1000)

        finished = self._clock.now()
        async with self._sessionmaker() as session, session.begin():
            row = await session.get(AIGeneration, generation_id, with_for_update=True)
            if row is None or row.status != "pending":
                return  # a parallel run (at-least-once delivery) got there first
            row.model = run.model
            row.attempts = run.attempts
            row.input_tokens = run.usage.input_tokens
            row.output_tokens = run.usage.output_tokens
            row.cache_read_tokens = run.usage.cache_read_tokens
            row.cache_write_tokens = run.usage.cache_write_tokens
            row.cost_micros = cost_micros(run.model, run.usage)
            row.latency_ms = latency_ms
            row.provider_request_id = run.provider_request_id
            if failure is not None:
                status = "provider_error"
            elif status == "validation_failed":
                row.validation_errors = run.errors
            elif draft is not None:
                proposal = build_proposal(
                    draft,
                    context,
                    destination=summary.model_dump(mode="json"),
                    destination_id=str(destination_id),
                    generated_at=finished,
                )
                row.result = ItineraryProposal.model_validate(proposal).model_dump(mode="json")
            self._close(row, status, finished)
            self._completed(session, row)

    async def _context(
        self, session: AsyncSession, row: AIGeneration
    ) -> tuple[ItineraryContext, DestinationSummary, uuid.UUID] | None:
        """The typed prompt context of a pending generation (AI-008: trip parameters, the
        trip's own items when replanning, and catalog places; nothing else)."""
        assert row.params is not None
        replan: Replan | None = None
        if row.feature == AITask.TRIP_REPLAN.value:
            plan = ReplanParams.model_validate(row.params)
            destination_id, start, end = plan.destination_id, plan.start_date, plan.end_date
            keep = set(plan.keep_item_ids)
            replan = Replan(
                instruction=plan.instruction,
                day_indexes=tuple(plan.day_indexes),
                current={
                    day.day_index: tuple(
                        CurrentItem(
                            title=item.title,
                            kind=item.kind,
                            start_time=item.start_time,
                            duration_minutes=item.duration_minutes,
                            place_id=str(item.place_id) if item.place_id else None,
                            keep=item.id in keep,
                        )
                        for item in day.items
                    )
                    for day in plan.current
                },
                avoid_categories=tuple(plan.avoid_categories),
            )
            fit: dict[str, Any] = {
                "interests": (),
                "travel_styles": (),
                "pace": plan.pace,
                "budget_level": "moderate",
                "adults": 1,
                "children": 0,
                "preferences": None,
                "include_social_opportunities": False,
            }
            referenced = [i.place_id for d in plan.current for i in d.items if i.place_id]
        else:
            request = GenerateItineraryRequest.model_validate(row.params)
            destination_id, start, end = (
                request.destination_id,
                request.start_date,
                request.end_date,
            )
            fit = {
                "interests": tuple(request.interests),
                "travel_styles": tuple(request.travel_styles),
                "pace": request.pace,
                "budget_level": request.budget_level,
                "adults": request.party.adults,
                "children": request.party.children,
                "preferences": request.preferences,
                "include_social_opportunities": request.include_social_opportunities,
            }
            referenced = []
        found = await destinations.planning_destination(session, destination_id, [row.locale])
        if found is None:
            return None
        summary, time_zone = found
        catalog = await destinations.place_candidates(session, destination_id, [row.locale])
        candidates = [
            Candidate(
                id=str(place.summary.id),
                name=place.summary.name,
                category=place.summary.category,
                summary=place.summary.model_dump(mode="json"),
                provider=place.provider,
                license=place.license,
                attribution_url=place.attribution_url,
                data_freshness_at=place.data_freshness_at,
            )
            for place in catalog
        ]
        # Places the trip already uses stay valid references when replanning.
        listed = {c.id for c in candidates}
        extra = [place_id for place_id in referenced if str(place_id) not in listed]
        for place in (await destinations.place_summaries(session, extra, [row.locale])).values():
            candidates.append(
                Candidate(
                    id=str(place.id),
                    name=place.name,
                    category=place.category,
                    summary=place.model_dump(mode="json"),
                )
            )
        context = ItineraryContext(
            destination_name=summary.name,
            destination_path=summary.path,
            country_name=summary.country_name,
            time_zone=time_zone,
            start_date=start,
            end_date=end,
            locale=row.locale,
            candidates=tuple(candidates),
            replan=replan,
            **fit,
        )
        return context, summary, destination_id

    async def _generate(
        self,
        provider: AIProvider,
        task: AITask,
        config: TaskConfig,
        context: ItineraryContext,
        run: _Run,
    ) -> tuple[str, ItineraryDraft | None]:
        """Call, validate, and retry once with the failed checks as feedback (architecture §13)."""
        prompt = build_prompt(context)
        feedback: str | None = None
        for _ in range(2):
            completion = await provider.complete(
                task=task,
                config=config,
                prompt=replace(prompt, feedback=feedback),
                schema=DRAFT_SCHEMA,
            )
            run.attempts += 1
            run.usage += completion.usage
            run.model = completion.model
            run.provider_request_id = completion.provider_request_id
            if completion.refused:
                return "refused", None
            if completion.stop_reason == "max_tokens":
                run.errors = ["the itinerary was cut off; keep descriptions and rationales shorter"]
            else:
                try:
                    draft = ItineraryDraft.model_validate_json(completion.text or "")
                except ValidationError as exc:
                    run.errors = schema_errors(exc)
                else:
                    run.errors = semantic_errors(draft, context)
                    if not run.errors:
                        return "succeeded", draft
            feedback = repair_feedback(run.errors)
        return "validation_failed", None


def _translation(
    post_id: uuid.UUID, source: str, target: str, text: str, model: str
) -> TranslationOut:
    return TranslationOut(
        post_id=post_id,
        source_language=source,
        target_language=target,
        text=text,
        provider_attribution=(
            "Machine translation by Claude (Anthropic)" if model.startswith("claude") else None
        ),
    )


def _lock_key(user_id: uuid.UUID) -> int:
    return int.from_bytes(user_id.bytes[:4], "big", signed=True)


def make_handlers(service: AIService) -> dict[str, platform.JobHandler]:
    async def handle(job: platform.Job) -> None:
        data = job.payload.get("data") or {}
        await service.run(uuid.UUID(str(data["generation_id"])))

    return {JOB_KIND: handle}


def subscribe(router: platform.EventRouter) -> None:
    router.subscribe(REQUESTED_EVENT, queue="default", kind=JOB_KIND)


async def purge_expired(session: AsyncSession) -> int:
    """Retention (docs/04 §14): stuck ``pending`` rows fail after a day, proposals go after 30
    days, telemetry after 13 months, cached post translations after 90 days."""
    stuck = await session.execute(
        update(AIGeneration)
        .where(AIGeneration.status == "pending", AIGeneration.created_at < platform.ago(days=1))
        .values(
            status="provider_error",
            error_code=ErrorCode.AI_UNAVAILABLE.value,
            completed_at=func.now(),
            params=None,
        )
    )
    proposals = await session.execute(
        update(AIGeneration)
        .where(AIGeneration.result.is_not(None), AIGeneration.created_at < platform.ago(days=30))
        .values(result=None)
    )
    removed = await platform.delete_batch(
        session, AIGeneration, AIGeneration.created_at < platform.ago(days=400)
    )
    translations = await platform.delete_batch(
        session, PostTranslation, PostTranslation.created_at < platform.ago(days=90)
    )
    return (
        int(getattr(stuck, "rowcount", 0) or 0)
        + int(getattr(proposals, "rowcount", 0) or 0)
        + removed
        + translations
    )


__all__ = [
    "COMPLETED_EVENT",
    "JOB_KIND",
    "REQUESTED_EVENT",
    "AIService",
    "SpendPolicy",
    "breaker_open",
    "make_handlers",
    "proposal_for",
    "purge_expired",
    "quota_status",
    "quota_usage",
    "subscribe",
]


async def export_user_data(
    session: AsyncSession, user_id: uuid.UUID
) -> dict[str, list[dict[str, object]]]:
    """Personal-data export (BL-6.03; AUTH-011): what this module holds about the user."""
    return {
        "ai_requests": await platform.export_rows(
            session,
            AIGeneration,
            AIGeneration.user_id == user_id,
            exclude=("provider_request_id", "request_id", "cost_micros"),
        ),
    }
