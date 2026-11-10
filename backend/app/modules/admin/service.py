"""Staff console operations (BL-1.14, ADM-001..003, SAFE-007).

Every mutation and sensitive read runs in ONE transaction with its audit entry. Enforcement
effects are applied through the owning modules (social for content, identity for accounts); the
admin module sits at the top layer so it may orchestrate them.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.pagination import CursorCodec, Page, PageInfo
from app.core.security.principal import ROLE_PERMISSIONS, Permission, PlatformRole
from app.core.time import Clock
from app.modules.admin.deps import Staff
from app.modules.admin.schemas import (
    AdminReport,
    AdminUser,
    ModerationActionOut,
    ModerationActionRequest,
    ResolveReportRequest,
    SuspendUserRequest,
)
from app.modules.identity import service as identity
from app.modules.messaging import service as messaging
from app.modules.observability import service as observability
from app.modules.platform import service as platform
from app.modules.profiles import service as profiles
from app.modules.social import service as social
from app.modules.trust_safety import service as trust_safety

CREATE_ACTION_ROUTE = "POST /v1/admin/moderation-actions"
_CONTENT_STATES = {
    "remove_content": "removed",
    "restore_content": "approved",
    "limit_visibility": "limited",
}
_ACCOUNT_STATUSES = {"suspend": "suspended", "ban": "deactivated", "reinstate": "active"}


def _invalid(field: str, message: str) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_FAILED,
        message,
        errors=[FieldError(field=field, code="invalid", message=message)],
    )


def _audit(
    session: AsyncSession,
    staff: Staff,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID,
    **metadata: Any,
) -> None:
    observability.audit(
        session,
        actor_id=staff.principal.user_id,
        actor_type="admin",
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        justification=staff.justification,
        metadata=metadata,
    )


class AdminService:
    def __init__(
        self, *, sessionmaker: async_sessionmaker[AsyncSession], cursors: CursorCodec, clock: Clock
    ) -> None:
        self._sessionmaker = sessionmaker
        self._cursors = cursors
        self._clock = clock

    # ─────────────────────────────── reports ───────────────────────────────

    async def list_reports(
        self,
        staff: Staff,
        *,
        status: str | None,
        reason: str | None,
        target_type: str | None,
        assigned_to: str | None,
        cursor: str | None,
        limit: int,
    ) -> Page[AdminReport]:
        assignee: uuid.UUID | str | None = None
        if assigned_to == "me":
            assignee = staff.principal.user_id
        elif assigned_to == "unassigned":
            assignee = "unassigned"
        elif assigned_to:
            try:
                assignee = uuid.UUID(assigned_to)
            except ValueError as exc:
                raise _invalid("/assigned_to", "A user ID, 'me' or 'unassigned'.") from exc
        filters = {
            "s": status,
            "r": reason,
            "t": target_type,
            "a": str(assignee) if assignee else None,
        }
        after = None
        if cursor:
            position = self._cursors.decode(cursor, scope="admin.reports")
            if position.get("f") != filters:
                raise AppError(ErrorCode.INVALID_CURSOR, "Cursor does not match these filters.")
            after = (
                int(position["p"]),
                datetime.fromisoformat(str(position["c"])),
                uuid.UUID(str(position["i"])),
            )
        async with self._sessionmaker() as session:
            rows = await trust_safety.report_queue(
                session,
                status=status,
                reason=reason,
                target_type=target_type,
                assigned_to=assignee,  # type: ignore[arg-type]
                after=after,
                limit=limit + 1,
            )
            has_more = len(rows) > limit
            rows = rows[:limit]
            data = await self._reports(session, rows)
        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            next_cursor = self._cursors.encode(
                {
                    "f": filters,
                    "p": last.priority,
                    "c": last.created_at.isoformat(),
                    "i": str(last.id),
                },
                scope="admin.reports",
            )
        return Page[AdminReport](
            data=data, page=PageInfo(next_cursor=next_cursor, has_more=has_more)
        )

    async def get_report(self, staff: Staff, report_id: uuid.UUID) -> AdminReport:
        """The evidence snapshot is sensitive: every view is audited with its justification."""
        async with self._sessionmaker() as session, session.begin():
            report = await trust_safety.get_report(session, report_id)
            if report is None:
                raise AppError(ErrorCode.NOT_FOUND, "Report not found.")
            _audit(session, staff, "report.viewed", "report", report.id)
            [out] = await self._reports(session, [report])
            return out

    async def assign(
        self, staff: Staff, report_id: uuid.UUID, assignee_id: uuid.UUID
    ) -> AdminReport:
        async with self._sessionmaker() as session, session.begin():
            report = await trust_safety.get_report(session, report_id, for_update=True)
            if report is None:
                raise AppError(ErrorCode.NOT_FOUND, "Report not found.")
            view = await identity.account_admin_view(session, assignee_id)
            if view is None or not any(
                Permission.MODERATION_REPORTS_MANAGE in ROLE_PERMISSIONS[PlatformRole(r)]
                for r in view.roles
                if r in PlatformRole._value2member_map_
            ):
                raise _invalid("/assignee_id", "The assignee must be a moderator.")
            report.assigned_to = assignee_id
            if report.status == "open":
                report.status = "in_review"
            _audit(
                session, staff, "report.assigned", "report", report.id, assignee_id=str(assignee_id)
            )
            await session.flush()
            [out] = await self._reports(session, [report])
            return out

    async def resolve(
        self, staff: Staff, report_id: uuid.UUID, request: ResolveReportRequest
    ) -> AdminReport:
        """Resolve, optionally applying a moderation action in the same transaction."""
        async with self._sessionmaker() as session, session.begin():
            report = await trust_safety.get_report(session, report_id, for_update=True)
            if report is None:
                raise AppError(ErrorCode.NOT_FOUND, "Report not found.")
            if report.status not in ("open", "in_review"):
                raise AppError(ErrorCode.CONFLICT, "This report is already resolved.")
            if request.action is not None:
                await self._apply(
                    session, staff, request.action.model_copy(update={"report_id": report.id})
                )
            report.status = request.status
            report.resolution_note = request.resolution_note
            report.resolved_by = staff.principal.user_id
            report.resolved_at = self._clock.now()
            _audit(session, staff, f"report.{request.status}", "report", report.id)
            await session.flush()
            [out] = await self._reports(session, [report])
            return out

    # ─────────────────────────────── moderation actions ───────────────────────────────

    async def create_action(
        self, staff: Staff, request: ModerationActionRequest, *, idempotency_key: uuid.UUID
    ) -> tuple[ModerationActionOut, bool]:
        async with self._sessionmaker() as session, session.begin():
            replay = await platform.idempotency.claim(
                session,
                user_id=staff.principal.user_id,
                key=idempotency_key,
                route=CREATE_ACTION_ROUTE,
                payload=request.model_dump(mode="json"),
            )
            if replay is not None:
                return ModerationActionOut.model_validate(replay.body), True
            out = await self._apply(session, staff, request)
            await platform.idempotency.complete(
                session,
                user_id=staff.principal.user_id,
                key=idempotency_key,
                status=201,
                body=out.model_dump(mode="json"),
            )
            return out, False

    async def list_actions(
        self, *, target_type: str, target_id: uuid.UUID, cursor: str | None, limit: int
    ) -> Page[ModerationActionOut]:
        scope = f"admin.actions.{target_type}.{target_id}"
        after = None
        if cursor:
            position = self._cursors.decode(cursor, scope=scope)
            after = (datetime.fromisoformat(str(position["c"])), uuid.UUID(str(position["i"])))
        async with self._sessionmaker() as session:
            rows = await trust_safety.actions_for(
                session, target_type=target_type, target_id=target_id, after=after, limit=limit + 1
            )
            has_more = len(rows) > limit
            rows = rows[:limit]
            data = await self._actions(session, rows)
        next_cursor = (
            self._cursors.encode(
                {"c": rows[-1].created_at.isoformat(), "i": str(rows[-1].id)}, scope=scope
            )
            if has_more and rows
            else None
        )
        return Page[ModerationActionOut](
            data=data, page=PageInfo(next_cursor=next_cursor, has_more=has_more)
        )

    async def _apply(
        self, session: AsyncSession, staff: Staff, request: ModerationActionRequest
    ) -> ModerationActionOut:
        action, target = request.action, request.target_type
        # The user the action affects (content author or the account), told via a notification.
        affected: uuid.UUID | None = request.target_id if target == "user" else None
        if (action == "restrict") != (request.restriction_kind is not None):
            raise _invalid(
                "/restriction_kind", "restriction_kind is required for (and only for) 'restrict'."
            )
        if action == "restrict" and target != "user":
            raise _invalid("/target_type", "'restrict' applies to users.")
        if action in _CONTENT_STATES and target == "message":
            if action == "limit_visibility":
                raise _invalid("/target_type", f"'{action}' does not apply to a {target}.")
            affected = await messaging.moderate_message(
                session, request.target_id, remove=action == "remove_content"
            )
        elif action in _CONTENT_STATES:
            if target not in ("post", "comment") or (
                action == "limit_visibility" and target != "post"
            ):
                raise _invalid("/target_type", f"'{action}' does not apply to a {target}.")
            affected = await social.moderate_content(
                session, target, request.target_id, _CONTENT_STATES[action]
            )
        elif action in _ACCOUNT_STATUSES:
            if target != "user":
                raise _invalid("/target_type", f"'{action}' applies to users.")
            if request.target_id == staff.principal.user_id:
                raise _invalid("/target_id", "You can't apply this to your own account.")
            await identity.set_account_status(
                session,
                request.target_id,
                status=_ACCOUNT_STATUSES[action],
                now=self._clock.now(),
                until=request.expires_at if action == "suspend" else None,
            )
        elif action == "remove_member":
            raise _invalid("/action", "Group moderation arrives with groups (Phase 5).")
        # warn is recorded and notified; restrict takes effect through active_restrictions.
        row = await trust_safety.record_action(
            session,
            target_type=target,
            target_id=request.target_id,
            action=action,
            reason_code=request.reason_code,
            notes=request.notes,
            actor_id=staff.principal.user_id,
            report_id=request.report_id,
            expires_at=request.expires_at,
            restriction_kind=request.restriction_kind,
        )
        _audit(
            session, staff, f"moderation.{action}", target, request.target_id, action_id=str(row.id)
        )
        platform.record_event(
            session,
            aggregate_type=target,
            aggregate_id=request.target_id,
            event_type="moderation.action_applied",
            payload={
                "action_id": str(row.id),
                "action": action,
                "target_type": target,
                "target_id": str(request.target_id),
                "reason_code": request.reason_code,
                "restriction_kind": request.restriction_kind,
                "user_id": str(affected) if affected else None,
            },
        )
        [out] = await self._actions(session, [row])
        return out

    # ─────────────────────────────── accounts ───────────────────────────────

    async def get_user(self, staff: Staff, user_id: uuid.UUID) -> AdminUser:
        async with self._sessionmaker() as session, session.begin():
            out = await self._user(session, user_id)
            _audit(session, staff, "user.viewed", "user", user_id)
            return out

    async def suspend(
        self, staff: Staff, user_id: uuid.UUID, request: SuspendUserRequest
    ) -> AdminUser:
        async with self._sessionmaker() as session, session.begin():
            await self._apply(
                session,
                staff,
                ModerationActionRequest(
                    target_type="user",
                    target_id=user_id,
                    action="suspend",
                    reason_code=request.reason_code,
                    notes=request.notes,
                    expires_at=request.until,
                ),
            )
            return await self._user(session, user_id)

    async def reinstate(self, staff: Staff, user_id: uuid.UUID, notes: str) -> AdminUser:
        async with self._sessionmaker() as session, session.begin():
            await self._apply(
                session,
                staff,
                ModerationActionRequest(
                    target_type="user",
                    target_id=user_id,
                    action="reinstate",
                    reason_code="reinstated",
                    notes=notes,
                ),
            )
            return await self._user(session, user_id)

    # ─────────────────────────────── assembly ───────────────────────────────

    async def _user(self, session: AsyncSession, user_id: uuid.UUID) -> AdminUser:
        view = await identity.account_admin_view(session, user_id)
        author = (await profiles.authors(session, [user_id])).get(user_id)
        if view is None or author is None:
            raise AppError(ErrorCode.NOT_FOUND, "User not found.")
        open_reports, actions = await trust_safety.user_moderation_counts(session, user_id)
        return AdminUser.model_validate(
            {
                "id": user_id,
                "handle": author.handle,
                "display_name": author.display_name,
                "status": view.status,
                "email": view.email,
                "roles": [r for r in view.roles if r in PlatformRole._value2member_map_],
                "created_at": view.created_at,
                "last_active_on": view.last_active_on,
                "open_report_count": open_reports,
                "moderation_action_count": actions,
                "suspended_until": view.suspended_until,
            }
        )

    async def _reports(self, session: AsyncSession, rows: Sequence[Any]) -> list[AdminReport]:
        people = await profiles.authors(
            session, [u for r in rows for u in (r.reporter_id, r.assigned_to) if u is not None]
        )
        related = await trust_safety.related_report_counts(session, rows)

        def summary(user_id: uuid.UUID | None) -> Any:
            return profiles.user_summary(people[user_id]) if user_id in people else None

        return [
            AdminReport.model_validate(
                {
                    "id": r.id,
                    "reporter": summary(r.reporter_id),
                    "target_type": r.target_type,
                    "target_id": r.target_id,
                    "reason": r.reason,
                    "details": r.details,
                    "priority": r.priority,
                    "status": r.status,
                    "assigned_to": summary(r.assigned_to),
                    "evidence": r.evidence,
                    "resolution_note": r.resolution_note,
                    "related_report_count": related.get(r.id, 0),
                    "created_at": r.created_at,
                    "resolved_at": r.resolved_at,
                }
            )
            for r in rows
        ]

    async def _actions(
        self, session: AsyncSession, rows: Sequence[Any]
    ) -> list[ModerationActionOut]:
        actors = await profiles.authors(session, [r.actor_id for r in rows if r.actor_id])
        return [
            ModerationActionOut.model_validate(
                {
                    "id": r.id,
                    "scope": r.scope,
                    "group_id": r.group_id,
                    "target_type": r.target_type,
                    "target_id": r.target_id,
                    "action": r.action,
                    "restriction_kind": r.restriction_kind,
                    "reason_code": r.reason_code,
                    "notes": r.notes,
                    "actor": profiles.user_summary(actors[r.actor_id])
                    if r.actor_id in actors
                    else None,
                    "report_id": r.report_id,
                    "expires_at": r.expires_at,
                    "created_at": r.created_at,
                }
            )
            for r in rows
        ]
