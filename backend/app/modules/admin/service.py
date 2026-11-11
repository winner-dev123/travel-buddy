"""Staff console operations (BL-1.14, ADM-001..003, SAFE-007).

Every mutation and sensitive read runs in ONE transaction with its audit entry. Enforcement
effects are applied through the owning modules (social for content, identity for accounts); the
admin module sits at the top layer so it may orchestrate them.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.pagination import CursorCodec, Page, PageInfo
from app.core.security.principal import ROLE_PERMISSIONS, Permission, PlatformRole
from app.core.time import Clock
from app.modules.admin.deps import Staff
from app.modules.admin.schemas import (
    AdminDestinationUpdate,
    AdminOverview,
    AdminReport,
    AdminUser,
    AdminUserSummary,
    AuditLogEntry,
    ModerationActionOut,
    ModerationActionRequest,
    OpsSummary,
    ResolveReportRequest,
    SuspendUserRequest,
)
from app.modules.billing import service as billing
from app.modules.billing.schemas import (
    AdminProductList,
    AdminProductOut,
    AdminTransactionPage,
    BillingPolicyOut,
    CreateProductRequest,
    EntitlementGrantList,
    EntitlementGrantOut,
    GrantEntitlementRequest,
    UpdateBillingPolicyRequest,
    UpdateProductRequest,
)
from app.modules.challenges import service as challenges
from app.modules.challenges.schemas import RewardDetail, RewardReviewRequest
from app.modules.destinations import service as destinations
from app.modules.destinations.schemas import Destination
from app.modules.identity import service as identity
from app.modules.identity.schemas import (
    AdminDataRequest,
    AdminDataRequestPage,
    RecordDataRequest,
    ResolveDataRequest,
)
from app.modules.media import service as media
from app.modules.media.schemas import EditorialMedia, EditorialRightsRequest
from app.modules.messaging import service as messaging
from app.modules.observability import service as observability
from app.modules.platform import service as platform
from app.modules.profiles import service as profiles
from app.modules.social import service as social
from app.modules.trust_safety import service as trust_safety
from app.modules.trust_safety.schemas import MessageFilterPolicyOut, UpdateMessageFilterRequest

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
    resource_id: uuid.UUID | str,
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


def _uuid_or_none(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


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

    async def search_users(
        self,
        staff: Staff,
        *,
        query: str | None,
        status: str | None,
        staff_only: bool,
        cursor: str | None,
        limit: int,
    ) -> Page[AdminUserSummary]:
        """Find accounts for the staff console (ADM-003). ``query`` is an exact email address, an
        account id, or the start of a handle / part of a display name; without it, accounts are
        listed newest first. Every search is audited with its filters."""
        text = (query or "").strip() or None
        filters = {"q": text, "status": status, "staff": staff_only}
        position = self._cursors.decode(cursor, scope="admin.users") if cursor is not None else None
        if position is not None and position.get("f") != filters:
            raise AppError(ErrorCode.INVALID_CURSOR, "The cursor belongs to another query.")
        next_position: dict[str, Any] | None = None
        async with self._sessionmaker() as session, session.begin():
            if text is None:
                after = (
                    (datetime.fromisoformat(str(position["c"])), uuid.UUID(str(position["i"])))
                    if position is not None
                    else None
                )
                rows = await identity.list_account_ids(
                    session, status=status, staff_only=staff_only, after=after, limit=limit + 1
                )
                if len(rows) > limit:
                    last_id, last_created = rows[limit - 1]
                    next_position = {"c": last_created.isoformat(), "i": str(last_id)}
                ids = [user_id for user_id, _ in rows[:limit]]
            elif "@" in text and " " not in text:
                found = await identity.user_id_by_email(session, text)
                ids = [found] if found is not None else []
            elif (as_id := _uuid_or_none(text)) is not None:
                ids = [as_id]
            else:
                people = await profiles.search_authors(
                    session,
                    text,
                    exclude=frozenset(),
                    after_handle=str(position["h"]) if position is not None else None,
                    limit=limit + 1,
                )
                if len(people) > limit:
                    next_position = {"h": people[limit - 1].handle}
                ids = [person.id for person in people[:limit]]
            summaries = await self._summaries(session, ids)
            _audit(session, staff, "users.searched", "user", "search", filters=filters)
        data = [
            s
            for s in summaries
            if (status is None or s.status == status) and (not staff_only or s.roles)
        ]
        next_cursor = (
            self._cursors.encode({"f": filters, **next_position}, scope="admin.users")
            if next_position is not None
            else None
        )
        return Page[AdminUserSummary](
            data=data, page=PageInfo(next_cursor=next_cursor, has_more=next_cursor is not None)
        )

    async def overview(self, staff: Staff) -> AdminOverview:
        """Console home page: real aggregates only (ADM-006). Billing totals and the privacy
        queue are left out for staff who may not open them."""
        now = self._clock.now()
        principal = staff.principal
        async with self._sessionmaker() as session:
            users = await identity.account_stats(session, now)
            premium = await billing.premium_member_count(session, now)
            posts = await social.posts_created_since(session, now - timedelta(days=7))
            queue = await trust_safety.report_queue_stats(session, now)
            data_requests = (
                await identity.open_data_request_count(session)
                if principal.has_permission(Permission.PRIVACY_REQUESTS_MANAGE)
                else None
            )
            revenue = (
                await billing.revenue_since(session, now - timedelta(days=30))
                if principal.has_permission(Permission.ENTITLEMENTS_GRANT)
                else None
            )
        return AdminOverview.model_validate(
            {
                "generated_at": now,
                "users": users,
                "premium_members": premium,
                "posts_7d": posts,
                "moderation": {
                    "open_reports": queue["open_reports"],
                    "unassigned_reports": queue["unassigned_reports"],
                    "oldest_open_age_seconds": queue["oldest_open_age_seconds"],
                    "by_priority": queue["open_by_priority"],
                },
                "open_data_requests": data_requests,
                "revenue_30d": [r.model_dump() for r in revenue] if revenue is not None else None,
            }
        )

    async def transactions(
        self,
        staff: Staff,
        *,
        user_id: uuid.UUID | None,
        status: str | None,
        cursor: str | None,
        limit: int,
    ) -> AdminTransactionPage:
        """The billing ledger for staff (ADM-005); audited, like every look at a user's money."""
        filters = {"user_id": str(user_id) if user_id else None, "status": status}
        after = None
        if cursor:
            position = self._cursors.decode(cursor, scope="admin.transactions")
            if position.get("f") != filters:
                raise AppError(ErrorCode.INVALID_CURSOR, "The cursor belongs to another query.")
            after = (datetime.fromisoformat(str(position["c"])), uuid.UUID(str(position["i"])))
        async with self._sessionmaker() as session, session.begin():
            rows = await billing.staff_transactions(
                session, user_id=user_id, status=status, after=after, limit=limit + 1
            )
            _audit(
                session,
                staff,
                "billing_transactions.viewed",
                "user" if user_id else "billing_transaction",
                user_id or "query",
                filters=filters,
            )
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            self._cursors.encode(
                {"f": filters, "c": rows[-1].occurred_at.isoformat(), "i": str(rows[-1].id)},
                scope="admin.transactions",
            )
            if has_more and rows
            else None
        )
        return AdminTransactionPage(
            data=rows, page=PageInfo(next_cursor=next_cursor, has_more=has_more)
        )

    async def assign_role(self, staff: Staff, user_id: uuid.UUID, role: str) -> AdminUser:
        """ADM-007: superadmins give platform roles; the account signs in again with a second
        factor before the role works."""
        async with self._sessionmaker() as session, session.begin():
            changed = await identity.assign_role(
                session, user_id, role, granted_by=staff.principal.user_id, now=self._clock.now()
            )
            if changed:
                _audit(session, staff, "staff_role.granted", "user", user_id, role=role)
            return await self._user(session, user_id)

    async def remove_role(self, staff: Staff, user_id: uuid.UUID, role: str) -> AdminUser:
        """Take a platform role away (sessions end at once). The last active superadmin keeps
        theirs, so the console can never lock everyone out."""
        async with self._sessionmaker() as session, session.begin():
            view = await identity.account_admin_view(session, user_id)
            if view is None:
                raise AppError(ErrorCode.NOT_FOUND, "User not found.")
            if (
                role == PlatformRole.SUPERADMIN
                and role in view.roles
                and await identity.active_role_holders(session, role) <= 1
            ):
                raise AppError(
                    ErrorCode.CONFLICT, "This is the last superadmin. Make someone else one first."
                )
            if await identity.remove_role(session, user_id, role, now=self._clock.now()):
                _audit(session, staff, "staff_role.revoked", "user", user_id, role=role)
            return await self._user(session, user_id)

    async def get_user(self, staff: Staff, user_id: uuid.UUID) -> AdminUser:
        async with self._sessionmaker() as session, session.begin():
            out = await self._user(session, user_id)
            _audit(session, staff, "user.viewed", "user", user_id)
            return out

    async def grants(self, staff: Staff, user_id: uuid.UUID) -> EntitlementGrantList:
        async with self._sessionmaker() as session, session.begin():
            if not await identity.is_active(session, user_id):
                raise AppError(ErrorCode.NOT_FOUND, "User not found.")
            data = await billing.staff_grants(session, user_id)
            _audit(session, staff, "entitlement_grants.viewed", "user", user_id)
        return EntitlementGrantList(data=data)

    async def grant(
        self, staff: Staff, user_id: uuid.UUID, request: GrantEntitlementRequest
    ) -> EntitlementGrantOut:
        """BILL-009: time-limited, audited with the reason and the staff justification."""
        async with self._sessionmaker() as session, session.begin():
            if not await identity.is_active(session, user_id):
                raise AppError(ErrorCode.NOT_FOUND, "User not found.")
            grant = await billing.grant_entitlement(
                session,
                user_id,
                key=request.entitlement_key,
                ends_at=request.ends_at,
                now=self._clock.now(),
            )
            _audit(
                session,
                staff,
                "entitlement.granted",
                "user",
                user_id,
                grant_id=str(grant.id),
                entitlement_key=grant.entitlement_key,
                ends_at=request.ends_at.isoformat(),
                reason=request.reason,
            )
        return grant

    async def data_requests(
        self,
        staff: Staff,
        *,
        state: str,
        kind: str | None,
        user_id: uuid.UUID | None,
        cursor: str | None,
        limit: int,
    ) -> AdminDataRequestPage:
        """SAFE-010 work queue; reading it is audited (the requests name people)."""
        filters = {"state": state, "kind": kind, "user_id": str(user_id) if user_id else None}
        after = None
        if cursor:
            position = self._cursors.decode(cursor, scope="admin.dsr")
            if position.get("f") != filters:
                raise AppError(ErrorCode.INVALID_CURSOR, "The cursor belongs to another query.")
            after = (datetime.fromisoformat(str(position["t"])), uuid.UUID(str(position["i"])))
        async with self._sessionmaker() as session, session.begin():
            rows = await identity.staff_data_requests(
                session,
                state=state,
                kind=kind,
                user_id=user_id,
                after=after,
                limit=limit + 1,
                now=self._clock.now(),
            )
            _audit(session, staff, "data_requests.viewed", "data_request", "query", filters=filters)
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            self._cursors.encode(
                {"f": filters, "t": rows[-1].requested_at.isoformat(), "i": str(rows[-1].id)},
                scope="admin.dsr",
            )
            if more and rows
            else None
        )
        return AdminDataRequestPage(
            data=rows, page=PageInfo(next_cursor=next_cursor, has_more=more)
        )

    async def record_data_request(
        self, staff: Staff, user_id: uuid.UUID, request: RecordDataRequest
    ) -> AdminDataRequest:
        async with self._sessionmaker() as session, session.begin():
            recorded = await identity.record_data_request(
                session, user_id, request, now=self._clock.now()
            )
            _audit(
                session,
                staff,
                "data_request.recorded",
                "data_request",
                recorded.id,
                user_id=str(user_id),
                kind=request.kind,
                channel=request.channel,
            )
        return recorded

    async def resolve_data_request(
        self, staff: Staff, request_id: uuid.UUID, resolution: ResolveDataRequest
    ) -> AdminDataRequest:
        async with self._sessionmaker() as session, session.begin():
            resolved = await identity.resolve_data_request(
                session,
                request_id,
                resolution,
                staff_id=staff.principal.user_id,
                now=self._clock.now(),
            )
            _audit(
                session,
                staff,
                "data_request.resolved",
                "data_request",
                request_id,
                user_id=str(resolved.user_id),
                status=resolution.status,
            )
        return resolved

    async def billing_policy(self) -> BillingPolicyOut:
        async with self._sessionmaker() as session:
            return await billing.billing_policy(session)

    async def update_billing_policy(
        self, staff: Staff, request: UpdateBillingPolicyRequest
    ) -> BillingPolicyOut:
        """Quota limits and the group admin grace, effective at once (BL-6.02); audited with
        the values before and after."""
        async with self._sessionmaker() as session, session.begin():
            before, after = await billing.update_billing_policy(
                session, request, staff_id=staff.principal.user_id, now=self._clock.now()
            )
            _audit(
                session,
                staff,
                "billing_policy.updated",
                "billing_policy",
                "entitlements",
                before=before.model_dump(mode="json", exclude={"updated_at", "updated_by"}),
                after=after.model_dump(mode="json", exclude={"updated_at", "updated_by"}),
            )
        return after

    async def revoke_grant(self, staff: Staff, grant_id: uuid.UUID) -> EntitlementGrantOut:
        async with self._sessionmaker() as session, session.begin():
            grant = await billing.revoke_staff_grant(session, grant_id, now=self._clock.now())
            _audit(session, staff, "entitlement.revoked", "entitlement_grant", grant_id)
        return grant

    async def products(self) -> AdminProductList:
        async with self._sessionmaker() as session:
            return AdminProductList(data=await billing.admin_products(session))

    async def create_product(self, staff: Staff, request: CreateProductRequest) -> AdminProductOut:
        async with self._sessionmaker() as session, session.begin():
            product = await billing.create_product(session, request)
            _audit(
                session,
                staff,
                "product.created",
                "product",
                product.id,
                **request.model_dump(mode="json"),
            )
        return product

    async def update_product(
        self, staff: Staff, product_id: uuid.UUID, request: UpdateProductRequest
    ) -> AdminProductOut:
        async with self._sessionmaker() as session, session.begin():
            product = await billing.update_product(session, product_id, request)
            _audit(
                session,
                staff,
                "product.updated",
                "product",
                product_id,
                **request.model_dump(mode="json", exclude_none=True),
            )
        return product

    async def ops_summary(self) -> OpsSummary:
        """ADM-006: moderation queue, outbox lag and job failures right now."""
        now = self._clock.now()
        async with self._sessionmaker() as session:
            moderation = await trust_safety.report_queue_stats(session, now)
            platform_stats = await platform.ops_stats(session, now)
        return OpsSummary(generated_at=now, moderation=moderation, **platform_stats)

    async def audit_logs(
        self,
        staff: Staff,
        *,
        resource_type: str | None,
        resource_id: uuid.UUID | None,
        actor_id: uuid.UUID | None,
        start: datetime | None,
        end: datetime | None,
        cursor: str | None,
        limit: int,
    ) -> Page[AuditLogEntry]:
        """Audit queries (ADM-002, SAFE-007); every query is itself audited."""
        filters = {
            "resource_type": resource_type,
            "resource_id": str(resource_id) if resource_id else None,
            "actor_id": str(actor_id) if actor_id else None,
            "from": start.isoformat() if start else None,
            "to": end.isoformat() if end else None,
        }
        after = None
        if cursor:
            position = self._cursors.decode(cursor, scope="admin.audit")
            if position.get("f") != filters:
                raise AppError(ErrorCode.INVALID_CURSOR, "The cursor belongs to another query.")
            after = (datetime.fromisoformat(str(position["c"])), uuid.UUID(str(position["i"])))
        async with self._sessionmaker() as session, session.begin():
            rows = list(
                await observability.query(
                    session,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    actor_id=actor_id,
                    start=start,
                    end=end,
                    after=after,
                    limit=limit + 1,
                )
            )
            _audit(session, staff, "audit_logs.viewed", "audit_log", "query", filters=filters)
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            self._cursors.encode(
                {"f": filters, "c": rows[-1].occurred_at.isoformat(), "i": str(rows[-1].id)},
                scope="admin.audit",
            )
            if has_more and rows
            else None
        )
        return Page[AuditLogEntry](
            data=[
                AuditLogEntry(
                    id=row.id,
                    occurred_at=row.occurred_at,
                    actor_id=row.actor_id,
                    actor_type=row.actor_type,  # type: ignore[arg-type]
                    action=row.action,
                    resource_type=row.resource_type,
                    resource_id=_uuid_or_none(row.resource_id),
                    scope_group_id=row.scope_group_id,
                    request_id=row.request_id,
                    metadata=row.details or {},
                )
                for row in rows
            ],
            page=PageInfo(next_cursor=next_cursor, has_more=has_more),
        )

    async def update_destination(
        self, staff: Staff, destination_id: uuid.UUID, request: AdminDestinationUpdate
    ) -> Destination:
        async with self._sessionmaker() as session, session.begin():
            updated = await destinations.admin_update(
                session,
                destination_id,
                is_featured=request.is_featured,
                status=request.status,
                cover_media_id=request.cover_media_id,
                set_cover=request.sets_cover,
            )
            _audit(
                session,
                staff,
                "destination.updated",
                "destination",
                destination_id,
                **request.model_dump(mode="json", exclude_unset=True),
            )
            return updated

    async def message_filter(self) -> MessageFilterPolicyOut:
        async with self._sessionmaker() as session:
            return await trust_safety.message_filter_policy(session)

    async def update_message_filter(
        self, staff: Staff, request: UpdateMessageFilterRequest
    ) -> MessageFilterPolicyOut:
        """Replace the new-connection keyword filter (SAFE-006), audited with what changed."""
        async with self._sessionmaker() as session, session.begin():
            before, after = await trust_safety.update_message_filter(
                session, request, staff_id=staff.principal.user_id
            )
            _audit(
                session,
                staff,
                "safety.message_filter.updated",
                "message_filter",
                "1",
                added=sorted(set(after.terms) - set(before.terms)),
                removed=sorted(set(before.terms) - set(after.terms)),
                new_connection_days=[before.new_connection_days, after.new_connection_days],
            )
            return after

    async def set_editorial_rights(
        self, staff: Staff, media_id: uuid.UUID, request: EditorialRightsRequest
    ) -> EditorialMedia:
        """Verify or revoke the rights of editorial media (DEST-007), audited with the staff
        justification. Revoking hides the image everywhere and purges cached pages using it."""
        async with self._sessionmaker() as session, session.begin():
            result = await media.set_editorial_rights(
                session,
                media_id,
                verified=request.verified,
                staff_id=staff.principal.user_id,
                attribution=request.attribution,
            )
            affected = await destinations.cover_rights_changed(session, media_id)
            _audit(
                session,
                staff,
                "media.rights_verified" if request.verified else "media.rights_revoked",
                "media",
                media_id,
                attribution=result.attribution.model_dump(mode="json"),
                destinations_affected=affected,
            )
            return result

    async def review_challenge_reward(
        self, staff: Staff, reward_id: uuid.UUID, request: RewardReviewRequest
    ) -> RewardDetail:
        """Discount and promotional rewards need this before their challenge is published
        (CHAL-014); audited with the staff justification."""
        async with self._sessionmaker() as session, session.begin():
            reviewed = await challenges.review_reward(session, reward_id, decision=request.decision)
            _audit(
                session,
                staff,
                f"challenge_reward.{request.decision}",
                "challenge_reward",
                reward_id,
                note=request.note,
            )
            return reviewed

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

    async def _summaries(
        self, session: AsyncSession, ids: Sequence[uuid.UUID]
    ) -> list[AdminUserSummary]:
        views = await identity.account_admin_views(session, ids)
        people = await profiles.authors(session, ids)
        return [
            AdminUserSummary.model_validate(
                {
                    "id": user_id,
                    "handle": people[user_id].handle,
                    "display_name": people[user_id].display_name,
                    "status": views[user_id].status,
                    "roles": [
                        r for r in views[user_id].roles if r in PlatformRole._value2member_map_
                    ],
                    "created_at": views[user_id].created_at,
                    "last_active_on": views[user_id].last_active_on,
                }
            )
            for user_id in ids
            if user_id in views and user_id in people and views[user_id].status != "deleted"
        ]

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
            session,
            [
                u
                for r in rows
                for u in (r.reporter_id, r.assigned_to, r.target_author_id)
                if u is not None
            ],
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
                    "target_author": summary(r.target_author_id),
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
