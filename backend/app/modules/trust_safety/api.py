"""HTTP adapters for blocks (``/v1/users/me/blocks``, ``/v1/users/{userId}/block``)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse

from app.core.pagination import Page
from app.core.security.authn import get_principal
from app.core.security.principal import Principal
from app.modules.profiles.schemas import UserSummary
from app.modules.trust_safety.schemas import CreateReportRequest, ReportReceipt
from app.modules.trust_safety.service import BlockService, ReportService

router = APIRouter(tags=["safety"])

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def _blocks(request: Request) -> BlockService:
    service: BlockService = request.app.state.block_service
    return service


@router.get("/v1/users/me/blocks", response_model=Page[UserSummary])
async def list_my_blocks(
    request: Request,
    principal: CurrentPrincipal,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> JSONResponse:
    page = await _blocks(request).list_blocked(principal.user_id, cursor=cursor, limit=limit)
    return JSONResponse(
        {
            "data": [u.model_dump(mode="json") for u in page.data],
            "page": page.page.model_dump(mode="json"),
        }
    )


@router.put("/v1/users/{user_id}/block", status_code=status.HTTP_204_NO_CONTENT)
async def block_user(user_id: uuid.UUID, request: Request, principal: CurrentPrincipal) -> Response:
    await _blocks(request).block(principal.user_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/v1/users/{user_id}/block", status_code=status.HTTP_204_NO_CONTENT)
async def unblock_user(
    user_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _blocks(request).unblock(principal.user_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _reports(request: Request) -> ReportService:
    service: ReportService = request.app.state.report_service
    return service


@router.post("/v1/reports", response_model=ReportReceipt, status_code=status.HTTP_202_ACCEPTED)
async def create_report(
    body: CreateReportRequest, request: Request, principal: CurrentPrincipal
) -> JSONResponse:
    receipt, created = await _reports(request).create(principal.user_id, body)
    return JSONResponse(
        receipt.model_dump(mode="json"),
        status_code=status.HTTP_202_ACCEPTED if created else status.HTTP_200_OK,
    )
