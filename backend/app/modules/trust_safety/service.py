"""Public interface of the trust_safety module: blocks (BL-1.12, SAFE-001).

A block is immediate and bidirectional. Modules above this layer (social, feed, messaging,
discovery) read :func:`blocked_ids` / :func:`is_blocked` to hide each user from the other, and
can register ``on_block`` hooks (wired by the composition root) that run in the SAME transaction,
e.g. removing follows in both directions. The blocked user is never notified.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.pagination import CursorCodec, Page, PageInfo
from app.modules.platform import service as platform
from app.modules.profiles import service as profiles
from app.modules.profiles.schemas import UserSummary
from app.modules.trust_safety.models import (
    ContentReport,
    ModerationAction,
    ReportStatus,
    UserBlock,
)
from app.modules.trust_safety.schemas import CreateReportRequest, ReportReceipt

BlockHook = Callable[[AsyncSession, uuid.UUID, uuid.UUID], Awaitable[None]]


async def is_blocked(session: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> bool:
    """True when either user blocked the other."""
    if a == b:
        return False
    found = await session.scalar(
        select(UserBlock.blocker_id).where(
            or_(
                and_(UserBlock.blocker_id == a, UserBlock.blocked_id == b),
                and_(UserBlock.blocker_id == b, UserBlock.blocked_id == a),
            )
        )
    )
    return found is not None


async def blocked_ids(session: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Everyone this user blocked or was blocked by: hide them from each other."""
    rows = await session.execute(
        select(UserBlock.blocker_id, UserBlock.blocked_id).where(
            or_(UserBlock.blocker_id == user_id, UserBlock.blocked_id == user_id)
        )
    )
    return {blocked if blocker == user_id else blocker for blocker, blocked in rows.all()}


async def blocks_of(
    session: AsyncSession, user_id: uuid.UUID
) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """(people this user blocked, people who blocked this user)."""
    rows = await session.execute(
        select(UserBlock.blocker_id, UserBlock.blocked_id).where(
            or_(UserBlock.blocker_id == user_id, UserBlock.blocked_id == user_id)
        )
    )
    mine: set[uuid.UUID] = set()
    theirs: set[uuid.UUID] = set()
    for blocker, blocked in rows.all():
        if blocker == user_id:
            mine.add(blocked)
        else:
            theirs.add(blocker)
    return mine, theirs


class BlockService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        cursors: CursorCodec,
        on_block: Sequence[BlockHook] = (),
    ) -> None:
        self._sessionmaker = sessionmaker
        self._cursors = cursors
        self._on_block = tuple(on_block)

    async def block(self, blocker_id: uuid.UUID, blocked_id: uuid.UUID) -> None:
        async with self._sessionmaker() as session, session.begin():
            await self.block_in(session, blocker_id, blocked_id)

    async def block_in(
        self, session: AsyncSession, blocker_id: uuid.UUID, blocked_id: uuid.UUID
    ) -> None:
        """Block inside the caller's transaction (also used by "report and block")."""
        if blocker_id == blocked_id:
            raise AppError(
                ErrorCode.VALIDATION_FAILED,
                "You can't block yourself.",
                errors=[FieldError(field="/userId", code="self", message="Cannot block yourself.")],
            )
        if blocked_id not in await profiles.authors(session, [blocked_id]):
            raise AppError(ErrorCode.NOT_FOUND, "User not found.")
        inserted = await session.execute(
            insert(UserBlock)
            .values(blocker_id=blocker_id, blocked_id=blocked_id)
            .on_conflict_do_nothing()
            .returning(UserBlock.blocker_id)
        )
        if inserted.first() is None:
            return  # already blocked: idempotent
        for hook in self._on_block:
            await hook(session, blocker_id, blocked_id)
        platform.record_event(
            session,
            aggregate_type="user",
            aggregate_id=blocker_id,
            event_type="user.blocked",
            payload={"blocker_id": str(blocker_id), "blocked_id": str(blocked_id)},
        )

    async def unblock(self, blocker_id: uuid.UUID, blocked_id: uuid.UUID) -> None:
        """Does not restore follows or connections."""
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                delete(UserBlock).where(
                    UserBlock.blocker_id == blocker_id, UserBlock.blocked_id == blocked_id
                )
            )

    async def list_blocked(
        self, blocker_id: uuid.UUID, *, cursor: str | None, limit: int
    ) -> Page[UserSummary]:
        scope = f"blocks.{blocker_id}"
        async with self._sessionmaker() as session:
            query = select(UserBlock).where(UserBlock.blocker_id == blocker_id)
            if cursor:
                position = self._cursors.decode(cursor, scope=scope)
                at = datetime.fromisoformat(str(position["at"]))
                other = uuid.UUID(str(position["id"]))
                query = query.where(
                    or_(
                        UserBlock.created_at < at,
                        and_(UserBlock.created_at == at, UserBlock.blocked_id < other),
                    )
                )
            rows = list(
                (
                    await session.scalars(
                        query.order_by(
                            UserBlock.created_at.desc(), UserBlock.blocked_id.desc()
                        ).limit(limit + 1)
                    )
                ).all()
            )
            has_more = len(rows) > limit
            rows = rows[:limit]
            users = await profiles.authors(session, [r.blocked_id for r in rows])
        data = [profiles.user_summary(users[r.blocked_id]) for r in rows if r.blocked_id in users]
        next_cursor = (
            self._cursors.encode(
                {"at": rows[-1].created_at.isoformat(), "id": str(rows[-1].blocked_id)},
                scope=scope,
            )
            if has_more and rows
            else None
        )
        return Page[UserSummary](
            data=data, page=PageInfo(next_cursor=next_cursor, has_more=has_more)
        )


# ─────────────────────────────── reports (SAFE-002/003) ───────────────────────────────


@dataclass(frozen=True, slots=True)
class Evidence:
    """What a reported target looked like when reported, and who is responsible for it."""

    author_id: uuid.UUID | None
    snapshot: dict[str, Any]


# Supplied by the composition root per target type (modules above this layer own the content).
# Returns None when the target does not exist or the reporter cannot see it.
EvidenceProvider = Callable[[AsyncSession, uuid.UUID, uuid.UUID], Awaitable[Evidence | None]]

# SAFE-003: minor safety, self-harm and threats first.
PRIORITY: dict[str, int] = {
    "minor_safety": 100,
    "self_harm": 90,
    "violence": 80,
    "sexual_content": 70,
    "hate": 60,
    "harassment": 60,
    "illegal": 60,
    "privacy_violation": 50,
    "impersonation": 40,
    "scam": 40,
    "spam": 20,
    "other": 10,
}
_OPEN = (ReportStatus.OPEN, ReportStatus.IN_REVIEW)


class ReportService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        blocks: BlockService,
        providers: Mapping[str, EvidenceProvider],
    ) -> None:
        self._sessionmaker = sessionmaker
        self._blocks = blocks
        self._providers = dict(providers)

    async def create(
        self, reporter_id: uuid.UUID, request: CreateReportRequest
    ) -> tuple[ReportReceipt, bool]:
        """Returns ``(receipt, created)``; a duplicate open report returns the existing one."""
        provider = self._providers.get(request.target_type)
        if provider is None:
            raise AppError(
                ErrorCode.VALIDATION_FAILED,
                "This kind of content can't be reported yet.",
                errors=[
                    FieldError(
                        field="/target_type", code="unsupported", message=request.target_type
                    )
                ],
            )
        if request.target_type == "user" and request.target_id == reporter_id:
            raise AppError(ErrorCode.VALIDATION_FAILED, "You can't report yourself.")
        async with self._sessionmaker() as session, session.begin():
            existing = await session.scalar(
                select(ContentReport).where(
                    ContentReport.reporter_id == reporter_id,
                    ContentReport.target_type == request.target_type,
                    ContentReport.target_id == request.target_id,
                    ContentReport.status.in_(_OPEN),
                )
            )
            if existing is not None:
                return _receipt(existing), False
            evidence = await provider(session, request.target_id, reporter_id)
            if evidence is None:
                raise AppError(ErrorCode.NOT_FOUND, "Not found.")
            report = ContentReport(
                reporter_id=reporter_id,
                target_type=request.target_type,
                target_id=request.target_id,
                target_author_id=evidence.author_id,
                reason=request.reason,
                details=request.details,
                priority=PRIORITY[request.reason],
                evidence=evidence.snapshot,
            )
            session.add(report)
            await session.flush()
            await session.refresh(report)
            if request.also_block and evidence.author_id and evidence.author_id != reporter_id:
                await self._blocks.block_in(session, reporter_id, evidence.author_id)
            platform.record_event(
                session,
                aggregate_type="report",
                aggregate_id=report.id,
                event_type="report.created",
                payload={"report_id": str(report.id), "priority": report.priority},
            )
            return _receipt(report), True


def _receipt(report: ContentReport) -> ReportReceipt:
    return ReportReceipt.model_validate(
        {"id": report.id, "status": report.status, "created_at": report.created_at}
    )


# ── staff queries (used by the admin module inside its own audited transactions) ──


async def report_queue(
    session: AsyncSession,
    *,
    status: str | None,
    reason: str | None,
    target_type: str | None,
    assigned_to: uuid.UUID | Literal["unassigned"] | None,
    after: tuple[int, datetime, uuid.UUID] | None,
    limit: int,
) -> list[ContentReport]:
    """Priority first, then oldest first (SAFE-003). Default: open and in-review reports."""
    query = select(ContentReport)
    query = query.where(
        ContentReport.status == status if status else ContentReport.status.in_(_OPEN)
    )
    if reason:
        query = query.where(ContentReport.reason == reason)
    if target_type:
        query = query.where(ContentReport.target_type == target_type)
    if assigned_to == "unassigned":
        query = query.where(ContentReport.assigned_to.is_(None))
    elif assigned_to is not None:
        query = query.where(ContentReport.assigned_to == assigned_to)
    if after is not None:
        priority, created, report_id = after
        query = query.where(
            or_(
                ContentReport.priority < priority,
                and_(ContentReport.priority == priority, ContentReport.created_at > created),
                and_(
                    ContentReport.priority == priority,
                    ContentReport.created_at == created,
                    ContentReport.id > report_id,
                ),
            )
        )
    query = query.order_by(
        ContentReport.priority.desc(), ContentReport.created_at, ContentReport.id
    ).limit(limit)
    return list((await session.scalars(query)).all())


async def get_report(
    session: AsyncSession, report_id: uuid.UUID, *, for_update: bool = False
) -> ContentReport | None:
    return await session.get(ContentReport, report_id, with_for_update=for_update)


async def related_report_counts(
    session: AsyncSession, reports: Sequence[ContentReport]
) -> dict[uuid.UUID, int]:
    """Other reports on the same target (signal of repeated abuse)."""
    counts: dict[uuid.UUID, int] = {}
    for report in reports:
        total = await session.scalar(
            select(func.count())
            .select_from(ContentReport)
            .where(
                ContentReport.target_type == report.target_type,
                ContentReport.target_id == report.target_id,
                ContentReport.id != report.id,
            )
        )
        counts[report.id] = int(total or 0)
    return counts


async def record_action(
    session: AsyncSession,
    *,
    target_type: str,
    target_id: uuid.UUID,
    action: str,
    reason_code: str,
    notes: str | None,
    actor_id: uuid.UUID,
    report_id: uuid.UUID | None,
    expires_at: datetime | None,
    restriction_kind: str | None = None,
) -> ModerationAction:
    row = ModerationAction(
        target_type=target_type,
        target_id=target_id,
        action=action,
        restriction_kind=restriction_kind,
        reason_code=reason_code,
        notes=notes,
        actor_id=actor_id,
        report_id=report_id,
        expires_at=expires_at,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def actions_for(
    session: AsyncSession,
    *,
    target_type: str,
    target_id: uuid.UUID,
    after: tuple[datetime, uuid.UUID] | None,
    limit: int,
) -> list[ModerationAction]:
    query = select(ModerationAction).where(
        ModerationAction.target_type == target_type, ModerationAction.target_id == target_id
    )
    if after is not None:
        query = query.where(
            or_(
                ModerationAction.created_at < after[0],
                and_(ModerationAction.created_at == after[0], ModerationAction.id < after[1]),
            )
        )
    query = query.order_by(ModerationAction.created_at.desc(), ModerationAction.id.desc())
    return list((await session.scalars(query.limit(limit))).all())


async def user_moderation_counts(session: AsyncSession, user_id: uuid.UUID) -> tuple[int, int]:
    """(open reports about the user or their content, moderation actions targeting the user)."""
    open_reports = await session.scalar(
        select(func.count())
        .select_from(ContentReport)
        .where(
            ContentReport.status.in_(_OPEN),
            or_(
                ContentReport.target_author_id == user_id,
                and_(ContentReport.target_type == "user", ContentReport.target_id == user_id),
            ),
        )
    )
    actions = await session.scalar(
        select(func.count())
        .select_from(ModerationAction)
        .where(ModerationAction.target_type == "user", ModerationAction.target_id == user_id)
    )
    return int(open_reports or 0), int(actions or 0)


@dataclass(frozen=True, slots=True)
class ActiveRestriction:
    kind: str
    reason_code: str
    until: datetime | None


async def active_restrictions(
    session: AsyncSession, user_id: uuid.UUID, *, now: datetime | None = None
) -> list[ActiveRestriction]:
    """``restrict`` actions on the account that have not expired and were not lifted by a later
    ``reinstate`` (SAFE-013). One entry per kind: the one lasting longest."""
    lifted_at = await session.scalar(
        select(func.max(ModerationAction.created_at)).where(
            ModerationAction.target_type == "user",
            ModerationAction.target_id == user_id,
            ModerationAction.action == "reinstate",
        )
    )
    query = select(ModerationAction).where(
        ModerationAction.target_type == "user",
        ModerationAction.target_id == user_id,
        ModerationAction.action == "restrict",
        or_(
            ModerationAction.expires_at.is_(None),
            ModerationAction.expires_at > (func.now() if now is None else now),
        ),
    )
    if lifted_at is not None:
        query = query.where(ModerationAction.created_at > lifted_at)
    best: dict[str, ActiveRestriction] = {}
    for row in (await session.scalars(query.order_by(ModerationAction.created_at))).all():
        kind = str(row.restriction_kind)
        current = best.get(kind)
        if current is None or (
            current.until is not None and (row.expires_at is None or row.expires_at > current.until)
        ):
            best[kind] = ActiveRestriction(kind, row.reason_code, row.expires_at)
    return [best[k] for k in sorted(best)]


async def ensure_not_restricted(
    session: AsyncSession, user_id: uuid.UUID, kind: str, *, message: str
) -> None:
    """Raise ``403 account_restricted`` when ``kind`` is active on the account."""
    if any(r.kind == kind for r in await active_restrictions(session, user_id)):
        raise AppError(ErrorCode.ACCOUNT_RESTRICTED, message)


async def purge_expired(session: AsyncSession) -> int:
    """Resolved reports (with their evidence) 12 months after resolution; moderation actions after
    3 years, except restrictions still in force (docs/04 §14). Legal holds arrive with BL-6.x."""
    still_in_force = (ModerationAction.action == "restrict") & (
        ModerationAction.expires_at.is_(None) | (ModerationAction.expires_at > func.now())
    )
    return await platform.delete_batch(
        session,
        ContentReport,
        ContentReport.resolved_at < platform.ago(days=365),
    ) + await platform.delete_batch(
        session,
        ModerationAction,
        (ModerationAction.created_at < platform.ago(days=3 * 365)) & ~still_in_force,
    )


async def reports_filed_since(
    session: AsyncSession, *, hours: int, at_least: int
) -> dict[uuid.UUID, int]:
    """Reporters who filed ``at_least`` reports in the last ``hours`` (mass reporting)."""
    rows = await session.execute(
        select(ContentReport.reporter_id, func.count())
        .where(
            ContentReport.reporter_id.is_not(None),
            ContentReport.created_at > func.now() - timedelta(hours=hours),
        )
        .group_by(ContentReport.reporter_id)
        .having(func.count() >= at_least)
    )
    return {reporter: count for reporter, count in rows.all() if reporter is not None}


async def file_system_report(
    session: AsyncSession, *, user_id: uuid.UUID, reason: str, signal: str, evidence: dict[str, Any]
) -> bool:
    """Queue an automated report about an account (no reporter), once per open signal."""
    already = await session.scalar(
        select(func.count())
        .select_from(ContentReport)
        .where(
            ContentReport.reporter_id.is_(None),
            ContentReport.target_type == "user",
            ContentReport.target_id == user_id,
            ContentReport.status.in_(_OPEN),
            ContentReport.evidence["signal"].astext == signal,
        )
    )
    if already:
        return False
    session.add(
        ContentReport(
            reporter_id=None,
            target_type="user",
            target_id=user_id,
            target_author_id=user_id,
            reason=reason,
            details=f"Automated abuse signal: {signal}",
            priority=PRIORITY[reason],
            evidence={"signal": signal, **evidence},
        )
    )
    await session.flush()
    return True
