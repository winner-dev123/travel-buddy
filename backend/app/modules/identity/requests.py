"""Staff handling of data subject requests (BL-6.03; SAFE-010, AUTH-011).

Exports and deletions run by themselves once requested; staff record requests that arrive by
email or post (an export on the user's behalf, or a rectification) and close rectifications
with the outcome told to the user. The legal deadline is one month (GDPR Art. 12(3)); the queue
shows the oldest open request first and flags overdue ones.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import Select, literal, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode, FieldError
from app.modules.identity.exports import ACTIVE, EXPORT_JOB
from app.modules.identity.models import (
    DataSubjectRequest,
    DataSubjectRequestKind,
    DataSubjectRequestStatus,
    User,
    UserStatus,
)
from app.modules.identity.schemas import AdminDataRequest, RecordDataRequest, ResolveDataRequest
from app.modules.platform import service as platform

DSR_DEADLINE = timedelta(days=30)


def _out(record: DataSubjectRequest, *, now: datetime) -> AdminDataRequest:
    due_at = record.requested_at + DSR_DEADLINE
    return AdminDataRequest(
        id=record.id,
        user_id=record.user_id,
        kind=record.kind,  # type: ignore[arg-type]
        status=record.status,  # type: ignore[arg-type]
        channel=record.channel,  # type: ignore[arg-type]
        details=record.reason,
        requested_at=record.requested_at,
        due_at=due_at,
        overdue=record.status in ACTIVE and due_at < now,
        scheduled_for=record.scheduled_for,
        completed_at=record.completed_at,
        handled_by=record.handled_by,
        resolution=record.resolution,
    )


async def staff_data_requests(
    session: AsyncSession,
    *,
    state: str,
    kind: str | None,
    user_id: uuid.UUID | None,
    after: tuple[datetime, uuid.UUID] | None,
    limit: int,
    now: datetime,
) -> list[AdminDataRequest]:
    """``state``: ``open`` (oldest first: the work queue), ``closed`` or ``all`` (newest first)."""
    query: Select[tuple[DataSubjectRequest]] = select(DataSubjectRequest)
    if state == "open":
        query = query.where(DataSubjectRequest.status.in_(ACTIVE))
    elif state == "closed":
        query = query.where(DataSubjectRequest.status.not_in(ACTIVE))
    if kind is not None:
        query = query.where(DataSubjectRequest.kind == kind)
    if user_id is not None:
        query = query.where(DataSubjectRequest.user_id == user_id)
    key = tuple_(DataSubjectRequest.requested_at, DataSubjectRequest.id)
    position = tuple_(literal(after[0]), literal(after[1])) if after is not None else None
    if state == "open":
        if position is not None:
            query = query.where(key > position)
        query = query.order_by(DataSubjectRequest.requested_at, DataSubjectRequest.id)
    else:
        if position is not None:
            query = query.where(key < position)
        query = query.order_by(DataSubjectRequest.requested_at.desc(), DataSubjectRequest.id.desc())
    rows = (await session.scalars(query.limit(limit))).all()
    return [_out(row, now=now) for row in rows]


def _conflict(message: str) -> AppError:
    return AppError(ErrorCode.CONFLICT, message)


async def record_data_request(
    session: AsyncSession, user_id: uuid.UUID, request: RecordDataRequest, *, now: datetime
) -> AdminDataRequest:
    status = await session.scalar(select(User.status).where(User.id == user_id))
    if status is None or status == UserStatus.DELETED:
        raise AppError(ErrorCode.NOT_FOUND, "User not found.")
    if request.kind == "rectification" and not request.details:
        message = "Describe what the user asked to correct."
        raise AppError(
            ErrorCode.VALIDATION_FAILED,
            message,
            errors=[FieldError(field="/details", code="required", message=message)],
        )
    if request.kind == "export":
        active = await session.scalar(
            select(DataSubjectRequest.id).where(
                DataSubjectRequest.user_id == user_id,
                DataSubjectRequest.kind == DataSubjectRequestKind.EXPORT,
                DataSubjectRequest.status.in_(ACTIVE),
            )
        )
        if active is not None:
            raise _conflict("An export for this user is already under way.")
    record = DataSubjectRequest(
        user_id=user_id,
        kind=request.kind,
        status=DataSubjectRequestStatus.RECEIVED,
        channel=request.channel,
        reason=request.details,
        requested_at=now,
    )
    session.add(record)
    try:
        await session.flush()
    except IntegrityError as exc:  # a concurrent export won the partial unique index
        raise _conflict("An export for this user is already under way.") from exc
    if request.kind == "export":
        # The same job as a self-service export: the user gets the in-app notice and link.
        await platform.enqueue(
            session,
            queue="default",
            kind=EXPORT_JOB,
            payload={"request_id": str(record.id)},
            dedupe_key=f"{EXPORT_JOB}:{record.id}",
        )
    return _out(record, now=now)


async def resolve_data_request(
    session: AsyncSession,
    request_id: uuid.UUID,
    resolution: ResolveDataRequest,
    *,
    staff_id: uuid.UUID,
    now: datetime,
) -> AdminDataRequest:
    record = await session.scalar(
        select(DataSubjectRequest).where(DataSubjectRequest.id == request_id).with_for_update()
    )
    if record is None:
        raise AppError(ErrorCode.NOT_FOUND, "Request not found.")
    if record.kind != DataSubjectRequestKind.RECTIFICATION:
        raise _conflict("Exports and deletions complete by themselves.")
    if record.status not in ACTIVE:
        raise _conflict("This request is already closed.")
    record.status = resolution.status
    record.resolution = resolution.resolution
    record.handled_by = staff_id
    record.completed_at = now
    await session.flush()
    return _out(record, now=now)
