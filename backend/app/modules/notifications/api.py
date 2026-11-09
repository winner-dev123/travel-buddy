"""``/v1/notifications``: list, unread count, mark read (NOTIF-001)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from app.core.i18n import negotiate_ui_locale, parse_accept_language
from app.core.security.authn import get_principal
from app.core.security.principal import Principal
from app.modules.notifications.schemas import (
    MarkNotificationsReadRequest,
    NotificationPage,
    UnreadCount,
)
from app.modules.notifications.service import NotificationService

router = APIRouter(prefix="/v1/notifications", tags=["notifications"])

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def _service(request: Request) -> NotificationService:
    service: NotificationService = request.app.state.notification_service
    return service


@router.get("", response_model=NotificationPage)
async def list_notifications(
    request: Request,
    principal: CurrentPrincipal,
    accept_language: Annotated[str | None, Header(alias="Accept-Language", max_length=200)] = None,
    unread_only: bool = False,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> NotificationPage:
    tags = parse_accept_language(accept_language)
    return await _service(request).list(
        principal.user_id,
        unread_only=unread_only,
        cursor=cursor,
        limit=limit,
        locale=negotiate_ui_locale(tags[0]) if tags else None,
    )


@router.get("/unread-count", response_model=UnreadCount)
async def unread_count(request: Request, principal: CurrentPrincipal) -> UnreadCount:
    return UnreadCount(count=await _service(request).unread_count(principal.user_id))


@router.post("/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    body: MarkNotificationsReadRequest, request: Request, principal: CurrentPrincipal
) -> Response:
    await _service(request).mark_read(principal.user_id, body.ids)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
