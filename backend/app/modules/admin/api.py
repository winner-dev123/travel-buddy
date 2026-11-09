"""HTTP adapters for ``/v1/admin/*`` (each route names its platform permission; ADM-007..009)."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import JSONResponse

from app.core.pagination import Page
from app.core.security.principal import Permission
from app.modules.admin.deps import Staff, staff
from app.modules.admin.schemas import (
    AdminReport,
    AdminUser,
    AssignReportRequest,
    ModerationActionOut,
    ModerationActionRequest,
    ReinstateUserRequest,
    ResolveReportRequest,
    SuspendUserRequest,
    TargetType,
)
from app.modules.admin.service import AdminService

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


@router.get("/users/{user_id}", response_model=AdminUser)
async def admin_get_user(
    user_id: uuid.UUID,
    request: Request,
    who: Annotated[Staff, Depends(staff(Permission.USERS_READ, justified=True))],
) -> AdminUser:
    return await _service(request).get_user(who, user_id)


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
