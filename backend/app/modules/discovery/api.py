"""``GET /v1/travelers/discover`` (BL-2.03)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse

from app.core.feature_flags import Flag, gate
from app.core.i18n import parse_accept_language
from app.core.ratelimit import rate_limited
from app.core.security.authn import get_principal
from app.core.security.principal import Principal
from app.modules.discovery.service import DiscoverParams, DiscoveryService

router = APIRouter(
    prefix="/v1/travelers", tags=["discovery"], dependencies=gate(Flag.TRAVELER_DISCOVERY)
)

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


@router.get("/discover", openapi_extra=rate_limited("discovery"))
async def discover_travelers(
    request: Request,
    principal: CurrentPrincipal,
    accept_language: Annotated[str | None, Header(alias="Accept-Language", max_length=200)] = None,
    scope: Literal["here_now", "upcoming"] = "here_now",
    destination_id: uuid.UUID | None = None,
    travel_start_date: date | None = None,
    travel_end_date: date | None = None,
    travel_style: Annotated[list[str] | None, Query(max_length=20)] = None,
    interest: Annotated[list[str] | None, Query(max_length=10)] = None,
    language: Annotated[list[str] | None, Query(max_length=10)] = None,
) -> JSONResponse:
    service: DiscoveryService = request.app.state.discovery_service
    cards = await service.discover(
        principal.user_id,
        DiscoverParams(
            scope=scope,
            destination_id=destination_id,
            travel_start_date=travel_start_date,
            travel_end_date=travel_end_date,
            travel_styles=tuple(travel_style or ()),
            interests=tuple(interest or ()),
            languages=tuple(language or ()),
        ),
        preferences=parse_accept_language(accept_language),
    )
    return JSONResponse(
        {
            "data": [card.model_dump(mode="json") for card in cards],
            "page": {"next_cursor": None, "has_more": False},
        }
    )
