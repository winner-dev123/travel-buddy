"""``/v1/connections``: requests inbox, send, accept/decline/cancel, connections (BL-2.04)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import JSONResponse

from app.core.pagination import Page
from app.core.ratelimit import rate_limited
from app.core.security.authn import get_principal
from app.core.security.principal import Principal
from app.modules.connections.domain import Action
from app.modules.connections.schemas import (
    ConnectionOut,
    ConnectionRequestOut,
    CreateConnectionRequestRequest,
    Status,
)
from app.modules.connections.service import ConnectionService

router = APIRouter(prefix="/v1/connections", tags=["connections"])

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def _service(request: Request) -> ConnectionService:
    service: ConnectionService = request.app.state.connection_service
    return service


@router.get("/requests", response_model=Page[ConnectionRequestOut])
async def list_requests(
    request: Request,
    principal: CurrentPrincipal,
    direction: Literal["incoming", "outgoing"] = "incoming",
    status_filter: Annotated[Status, Query(alias="status")] = "pending",
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[ConnectionRequestOut]:
    return await _service(request).list_requests(
        principal.user_id, direction=direction, status=status_filter, cursor=cursor, limit=limit
    )


@router.post(
    "/requests",
    status_code=status.HTTP_201_CREATED,
    response_model=ConnectionRequestOut,
    openapi_extra=rate_limited("contact"),
)
async def send_request(
    body: CreateConnectionRequestRequest,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
) -> JSONResponse:
    out, replayed = await _service(request).create_request(
        principal, body, idempotency_key=idempotency_key
    )
    headers = {"Idempotent-Replayed": "true"} if replayed else {}
    return JSONResponse(
        out.model_dump(mode="json"), status_code=status.HTTP_201_CREATED, headers=headers
    )


@router.post("/requests/{connection_request_id}/accept", response_model=ConnectionOut)
async def accept_request(
    connection_request_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> ConnectionOut:
    connection = await _service(request).respond(
        principal.user_id, connection_request_id, Action.ACCEPT
    )
    assert connection is not None
    return connection


@router.post("/requests/{connection_request_id}/decline", status_code=status.HTTP_204_NO_CONTENT)
async def decline_request(
    connection_request_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _service(request).respond(principal.user_id, connection_request_id, Action.DECLINE)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/requests/{connection_request_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_request(
    connection_request_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _service(request).respond(principal.user_id, connection_request_id, Action.CANCEL)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("", response_model=Page[ConnectionOut])
async def list_connections(
    request: Request,
    principal: CurrentPrincipal,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[ConnectionOut]:
    return await _service(request).list_connections(principal.user_id, cursor=cursor, limit=limit)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_connection(
    user_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _service(request).remove(principal.user_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
