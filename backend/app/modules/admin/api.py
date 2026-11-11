"""HTTP adapters for ``/v1/admin/*`` (each route names its platform permission; ADM-007..009)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import JSONResponse

from app.core.pagination import Page
from app.core.security.principal import Permission
from app.modules.admin.deps import Staff, staff
from app.modules.admin.schemas import (
    AccountStatus,
    AdminDestinationUpdate,
    AdminOverview,
    AdminReport,
    AdminUser,
    AdminUserSummary,
    AssignReportRequest,
    AuditLogEntry,
    ModerationActionOut,
    ModerationActionRequest,
    OpsSummary,
    ReinstateUserRequest,
    ResolveReportRequest,
    StaffRole,
    SuspendUserRequest,
    TargetType,
)
from app.modules.admin.service import AdminService
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
from app.modules.challenges.schemas import RewardDetail, RewardReviewRequest
from app.modules.destinations.schemas import Destination
from app.modules.identity.schemas import (
    AdminDataRequest,
    AdminDataRequestPage,
    RecordDataRequest,
    ResolveDataRequest,
)
from app.modules.media.schemas import EditorialMedia, EditorialRightsRequest
from app.modules.trust_safety.schemas import MessageFilterPolicyOut, UpdateMessageFilterRequest

router = APIRouter(prefix="/v1/admin", tags=["admin"])

Cursor = Annotated[str | None, Query(max_length=1024)]
Limit = Annotated[int, Query(ge=1, le=100)]


def _service(request: Request) -> AdminService:
    service: AdminService = request.app.state.admin_service
    return service


def _page(page: Page[Any]) -> JSONResponse:
    return JSONResponse(
        {
            "data": [item.model_dump(mode="json") for item in page.data],
            "page": page.page.model_dump(mode="json"),
        }
    )


@router.get("/reports", response_model=Page[AdminReport])
async def admin_list_reports(
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.MODERATION_REPORTS_READ))],
    status_filter: Annotated[
        Literal["open", "in_review", "actioned", "dismissed"] | None, Query(alias="status")
    ] = None,
    reason: Annotated[str | None, Query(max_length=40)] = None,
    target_type: TargetType | None = None,
    assigned_to: Annotated[str | None, Query(max_length=40)] = None,
    cursor: Cursor = None,
    limit: Limit = 20,
) -> JSONResponse:
    page = await _service(request).list_reports(
        who,
        status=status_filter,
        reason=reason,
        target_type=target_type,
        assigned_to=assigned_to,
        cursor=cursor,
        limit=limit,
    )
    return _page(page)


@router.get("/reports/{report_id}", response_model=AdminReport)
async def admin_get_report(
    report_id: uuid.UUID,
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.MODERATION_REPORTS_READ, justified=True))],
) -> AdminReport:
    return await _service(request).get_report(who, report_id)


@router.post("/reports/{report_id}/assign", response_model=AdminReport)
async def admin_assign_report(
    report_id: uuid.UUID,
    body: AssignReportRequest,
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.MODERATION_REPORTS_MANAGE, justified=True))],
) -> AdminReport:
    return await _service(request).assign(who, report_id, body.assignee_id)


@router.post("/reports/{report_id}/resolve", response_model=AdminReport)
async def admin_resolve_report(
    report_id: uuid.UUID,
    body: ResolveReportRequest,
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.MODERATION_REPORTS_MANAGE, justified=True))],
) -> AdminReport:
    return await _service(request).resolve(who, report_id, body)


@router.get("/moderation-actions", response_model=Page[ModerationActionOut])
async def admin_list_moderation_actions(
    request: Request,
    _who: Annotated[Staff, Depends(staff(Permission.MODERATION_ACTIONS_READ))],
    target_type: TargetType,
    target_id: uuid.UUID,
    cursor: Cursor = None,
    limit: Limit = 20,
) -> JSONResponse:
    page = await _service(request).list_actions(
        target_type=target_type, target_id=target_id, cursor=cursor, limit=limit
    )
    return _page(page)


@router.post(
    "/moderation-actions",
    status_code=status.HTTP_201_CREATED,
    response_model=ModerationActionOut,
)
async def admin_create_moderation_action(
    body: ModerationActionRequest,
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.MODERATION_ACTIONS_WRITE, justified=True))],
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
) -> JSONResponse:
    action, replayed = await _service(request).create_action(
        who, body, idempotency_key=idempotency_key
    )
    return JSONResponse(
        action.model_dump(mode="json"),
        status_code=status.HTTP_201_CREATED,
        headers={"Idempotent-Replayed": "true"} if replayed else {},
    )


@router.get("/metrics/overview", response_model=AdminOverview)
async def admin_overview(
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.USERS_READ))],
) -> AdminOverview:
    return await _service(request).overview(who)


@router.get("/users", response_model=Page[AdminUserSummary])
async def admin_search_users(
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.USERS_READ, justified=True))],
    q: Annotated[str | None, Query(max_length=320)] = None,
    status_filter: Annotated[AccountStatus | None, Query(alias="status")] = None,
    staff_only: Annotated[bool, Query(alias="staff")] = False,
    cursor: Cursor = None,
    limit: Limit = 20,
) -> JSONResponse:
    page = await _service(request).search_users(
        who, query=q, status=status_filter, staff_only=staff_only, cursor=cursor, limit=limit
    )
    return _page(page)


@router.get("/billing/transactions", response_model=AdminTransactionPage)
async def admin_list_transactions(
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.ENTITLEMENTS_GRANT, justified=True))],
    user_id: uuid.UUID | None = None,
    status_filter: Annotated[
        Literal["pending", "succeeded", "failed", "open", "won", "lost"] | None,
        Query(alias="status"),
    ] = None,
    cursor: Cursor = None,
    limit: Limit = 20,
) -> AdminTransactionPage:
    return await _service(request).transactions(
        who, user_id=user_id, status=status_filter, cursor=cursor, limit=limit
    )


@router.put("/users/{user_id}/roles/{role}", response_model=AdminUser)
async def admin_assign_role(
    user_id: uuid.UUID,
    role: StaffRole,
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.ROLES_ASSIGN, justified=True))],
) -> AdminUser:
    return await _service(request).assign_role(who, user_id, role)


@router.delete("/users/{user_id}/roles/{role}", response_model=AdminUser)
async def admin_remove_role(
    user_id: uuid.UUID,
    role: StaffRole,
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.ROLES_ASSIGN, justified=True))],
) -> AdminUser:
    return await _service(request).remove_role(who, user_id, role)


@router.get("/users/{user_id}", response_model=AdminUser)
async def admin_get_user(
    user_id: uuid.UUID,
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.USERS_READ, justified=True))],
) -> AdminUser:
    return await _service(request).get_user(who, user_id)


@router.get("/users/{user_id}/entitlement-grants", response_model=EntitlementGrantList)
async def admin_list_entitlement_grants(
    user_id: uuid.UUID,
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.ENTITLEMENTS_GRANT, justified=True))],
) -> EntitlementGrantList:
    return await _service(request).grants(who, user_id)


@router.post(
    "/users/{user_id}/entitlement-grants",
    status_code=status.HTTP_201_CREATED,
    response_model=EntitlementGrantOut,
)
async def admin_grant_entitlement(
    user_id: uuid.UUID,
    body: GrantEntitlementRequest,
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.ENTITLEMENTS_GRANT, justified=True))],
) -> EntitlementGrantOut:
    return await _service(request).grant(who, user_id, body)


@router.post("/entitlement-grants/{grant_id}/revoke", response_model=EntitlementGrantOut)
async def admin_revoke_entitlement_grant(
    grant_id: uuid.UUID,
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.ENTITLEMENTS_GRANT, justified=True))],
) -> EntitlementGrantOut:
    return await _service(request).revoke_grant(who, grant_id)


@router.get("/data-requests", response_model=AdminDataRequestPage)
async def admin_list_data_requests(
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.PRIVACY_REQUESTS_MANAGE, justified=True))],
    state: Literal["open", "closed", "all"] = "open",
    kind: Literal["export", "deletion", "rectification"] | None = None,
    user_id: uuid.UUID | None = None,
    cursor: Cursor = None,
    limit: Limit = 20,
) -> AdminDataRequestPage:
    return await _service(request).data_requests(
        who, state=state, kind=kind, user_id=user_id, cursor=cursor, limit=limit
    )


@router.post(
    "/users/{user_id}/data-requests",
    status_code=status.HTTP_201_CREATED,
    response_model=AdminDataRequest,
)
async def admin_record_data_request(
    user_id: uuid.UUID,
    body: RecordDataRequest,
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.PRIVACY_REQUESTS_MANAGE, justified=True))],
) -> AdminDataRequest:
    return await _service(request).record_data_request(who, user_id, body)


@router.post("/data-requests/{request_id}/resolve", response_model=AdminDataRequest)
async def admin_resolve_data_request(
    request_id: uuid.UUID,
    body: ResolveDataRequest,
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.PRIVACY_REQUESTS_MANAGE, justified=True))],
) -> AdminDataRequest:
    return await _service(request).resolve_data_request(who, request_id, body)


@router.get("/billing/policy", response_model=BillingPolicyOut)
async def admin_get_billing_policy(
    request: Request,
    _who: Annotated[Staff, Depends(staff(Permission.BILLING_CONFIGURE))],
) -> BillingPolicyOut:
    return await _service(request).billing_policy()


@router.put("/billing/policy", response_model=BillingPolicyOut)
async def admin_update_billing_policy(
    body: UpdateBillingPolicyRequest,
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.BILLING_CONFIGURE, justified=True))],
) -> BillingPolicyOut:
    return await _service(request).update_billing_policy(who, body)


@router.get("/products", response_model=AdminProductList)
async def admin_list_products(
    request: Request,
    _who: Annotated[Staff, Depends(staff(Permission.BILLING_CONFIGURE))],
) -> AdminProductList:
    return await _service(request).products()


@router.post("/products", status_code=status.HTTP_201_CREATED, response_model=AdminProductOut)
async def admin_create_product(
    body: CreateProductRequest,
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.BILLING_CONFIGURE, justified=True))],
) -> AdminProductOut:
    return await _service(request).create_product(who, body)


@router.patch("/products/{product_id}", response_model=AdminProductOut)
async def admin_update_product(
    product_id: uuid.UUID,
    body: UpdateProductRequest,
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.BILLING_CONFIGURE, justified=True))],
) -> AdminProductOut:
    return await _service(request).update_product(who, product_id, body)


@router.get("/ops/summary", response_model=OpsSummary)
async def admin_ops_summary(
    request: Request,
    _who: Annotated[Staff, Depends(staff(Permission.AUDIT_READ))],
) -> OpsSummary:
    return await _service(request).ops_summary()


@router.get("/audit-logs", response_model=Page[AuditLogEntry])
async def admin_list_audit_logs(
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.AUDIT_READ, justified=True))],
    resource_type: Annotated[str | None, Query(max_length=60)] = None,
    resource_id: uuid.UUID | None = None,
    actor_id: uuid.UUID | None = None,
    start: Annotated[datetime | None, Query(alias="from")] = None,
    end: Annotated[datetime | None, Query(alias="to")] = None,
    cursor: Cursor = None,
    limit: Limit = 20,
) -> JSONResponse:
    page = await _service(request).audit_logs(
        who,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_id=actor_id,
        start=start,
        end=end,
        cursor=cursor,
        limit=limit,
    )
    return _page(page)


@router.patch("/destinations/{destination_id}", response_model=Destination)
async def admin_update_destination(
    destination_id: uuid.UUID,
    body: AdminDestinationUpdate,
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.CONTENT_DESTINATIONS_WRITE, justified=True))],
) -> Destination:
    return await _service(request).update_destination(who, destination_id, body)


@router.get("/safety/message-filter", response_model=MessageFilterPolicyOut)
async def admin_get_message_filter(
    request: Request,
    _who: Annotated[Staff, Depends(staff(Permission.SAFETY_FILTERS_MANAGE))],
) -> MessageFilterPolicyOut:
    return await _service(request).message_filter()


@router.put("/safety/message-filter", response_model=MessageFilterPolicyOut)
async def admin_update_message_filter(
    body: UpdateMessageFilterRequest,
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.SAFETY_FILTERS_MANAGE, justified=True))],
) -> MessageFilterPolicyOut:
    return await _service(request).update_message_filter(who, body)


@router.post("/media/{media_id}/rights", response_model=EditorialMedia)
async def admin_set_editorial_rights(
    media_id: uuid.UUID,
    body: EditorialRightsRequest,
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.CONTENT_DESTINATIONS_WRITE, justified=True))],
) -> EditorialMedia:
    return await _service(request).set_editorial_rights(who, media_id, body)


@router.post("/challenge-rewards/{reward_id}/review", response_model=RewardDetail)
async def admin_review_challenge_reward(
    reward_id: uuid.UUID,
    body: RewardReviewRequest,
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.CONTENT_REWARDS_REVIEW, justified=True))],
) -> RewardDetail:
    return await _service(request).review_challenge_reward(who, reward_id, body)


@router.post("/users/{user_id}/suspend", response_model=AdminUser)
async def admin_suspend_user(
    user_id: uuid.UUID,
    body: SuspendUserRequest,
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.USERS_SUSPEND, justified=True))],
) -> AdminUser:
    return await _service(request).suspend(who, user_id, body)


@router.post("/users/{user_id}/reinstate", response_model=AdminUser)
async def admin_reinstate_user(
    user_id: uuid.UUID,
    body: ReinstateUserRequest,
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.USERS_SUSPEND, justified=True))],
) -> AdminUser:
    return await _service(request).reinstate(who, user_id, body.notes)
