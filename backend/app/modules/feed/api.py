"""HTTP adapters for ``GET /v1/feed`` and ``POST /v1/feed/feedback``."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import JSONResponse

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.i18n import LOCALE_TAG_PATTERN, parse_accept_language
from app.core.security.authn import get_principal
from app.core.security.principal import Principal
from app.modules.destinations import service as destinations
from app.modules.feed.schemas import FeedFeedbackRequest
from app.modules.feed.service import FeedParams, FeedService

router = APIRouter(tags=["feed"])

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
_KINDS = frozenset(
    {
        "text",
        "photo",
        "video",
        "story",
        "attraction_recommendation",
        "restaurant_recommendation",
        "review",
        "tip",
        "itinerary_summary",
        "experience",
    }
)


def _service(request: Request) -> FeedService:
    service: FeedService = request.app.state.feed_service
    return service


def _csv(raw: str | None) -> list[str]:
    return list(dict.fromkeys(v.strip() for v in (raw or "").split(",") if v.strip()))


def _reject(field: str, message: str) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_FAILED,
        message,
        errors=[FieldError(field=field, code="invalid", message=message)],
    )


@router.get("/v1/feed")
async def get_feed(
    request: Request,
    principal: CurrentPrincipal,
    accept_language: Annotated[str | None, Header(alias="Accept-Language", max_length=200)] = None,
    tab: Literal["for_you", "nearby", "following", "destinations"] = "for_you",
    destination_id: UUID | None = None,
    near: Annotated[str | None, Query(max_length=40)] = None,
    near_ts: datetime | None = None,
    near_accuracy_m: Annotated[float | None, Query(ge=0, le=100_000)] = None,
    radius_km: Annotated[int, Query(ge=1, le=50)] = 10,
    country: Annotated[str | None, Query(pattern=r"^[A-Z]{2}$")] = None,
    category: Annotated[str | None, Query(max_length=300)] = None,
    tag: Annotated[str | None, Query(max_length=220)] = None,
    language: Annotated[str | None, Query(max_length=200)] = None,
    sort: Literal["ranked", "recent", "popular"] = "ranked",
    saved_destinations_only: bool = False,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> JSONResponse:
    kinds = _csv(category)
    if set(kinds) - _KINDS:
        raise _reject("/category", "Unknown post category.")
    tags = [t.lower() for t in _csv(tag)]
    if len(tags) > 5 or any(len(t) > 40 for t in tags):
        raise _reject("/tag", "Up to 5 tags of at most 40 characters.")
    languages = _csv(language)
    if any(not re.fullmatch(LOCALE_TAG_PATTERN, lang) for lang in languages):
        raise _reject("/language", "Use BCP 47 language tags such as pt-BR.")
    result = await _service(request).feed(
        principal.user_id,
        FeedParams(
            tab=tab,
            destination_id=destination_id,
            near=near,
            near_ts=near_ts,
            near_city_level=destinations.city_level_only(near_accuracy_m),
            radius_km=radius_km,
            country=country,
            kinds=tuple(kinds),
            tags=tuple(tags),
            languages=tuple(languages) if language is not None else None,
            sort=sort,
            saved_destinations_only=saved_destinations_only,
            cursor=cursor,
            limit=limit,
        ),
        preferences=parse_accept_language(accept_language),
    )
    return JSONResponse(
        {
            "data": result.data,
            "page": {
                "next_cursor": result.next_cursor,
                "has_more": result.has_more,
                "reset": result.reset,
            },
            "context": result.context.model_dump(mode="json"),
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/v1/feed/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def submit_feed_feedback(
    body: FeedFeedbackRequest, request: Request, principal: CurrentPrincipal
) -> Response:
    await _service(request).feedback(principal.user_id, body)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
