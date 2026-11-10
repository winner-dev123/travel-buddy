"""``POST /v1/realtime/tickets``: single-use WebSocket tickets for browsers (ADR-0013, BL-3.15)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.ratelimit import rate_limited
from app.core.security.authn import get_principal
from app.core.security.principal import Principal
from app.modules.identity import service as identity
from app.realtime.frames import timestamp

router = APIRouter(prefix="/v1/realtime", tags=["realtime"])


class RealtimeTicket(BaseModel):
    ticket: str
    expires_at: datetime


@router.post(
    "/tickets",
    status_code=status.HTTP_201_CREATED,
    response_model=RealtimeTicket,
    openapi_extra=rate_limited("realtime_ticket"),
)
async def create_realtime_ticket(
    request: Request, principal: Annotated[Principal, Depends(get_principal)]
) -> JSONResponse:
    async with request.app.state.database.sessionmaker() as session, session.begin():
        ticket, expires_at = await identity.mint_realtime_ticket(
            session, principal, now=request.app.state.clock.now()
        )
    return JSONResponse(
        {"ticket": ticket, "expires_at": timestamp(expires_at)},
        status_code=status.HTTP_201_CREATED,
        headers={"Cache-Control": "no-store"},
    )
