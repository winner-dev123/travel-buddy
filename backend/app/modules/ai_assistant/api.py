"""``/v1/ai``: itinerary generation and generation polling (BL-4.02)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import JSONResponse

from app.core.i18n import negotiate_ui_locale, parse_accept_language
from app.core.ratelimit.http import rate_limited
from app.core.security.authn import get_principal
from app.core.security.principal import Principal
from app.modules.ai_assistant.schemas import (
    AIGenerationOut,
    GenerateItineraryRequest,
    TranslationOut,
)
from app.modules.ai_assistant.service import AIService

router = APIRouter(prefix="/v1/ai", tags=["ai"])

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def _service(request: Request) -> AIService:
    service: AIService = request.app.state.ai_service
    return service


@router.post(
    "/itineraries/generate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AIGenerationOut,
    openapi_extra=rate_limited("ai"),
)
async def generate_itinerary(
    body: GenerateItineraryRequest,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
    accept_language: Annotated[str | None, Header(alias="Accept-Language")] = None,
) -> JSONResponse:
    tags = parse_accept_language(accept_language)
    locale = negotiate_ui_locale(tags[0] if tags else None)
    generation = await _service(request).generate_itinerary(
        principal, body, idempotency_key=idempotency_key, locale=locale
    )
    return JSONResponse(
        generation.model_dump(mode="json"),
        status_code=status.HTTP_202_ACCEPTED,
        headers={"Location": f"/v1/ai/generations/{generation.id}"},
    )


@router.get("/generations/{generation_id}", response_model=AIGenerationOut)
async def get_generation(
    generation_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> AIGenerationOut:
    return await _service(request).get(principal.user_id, generation_id)


# Machine translation of a post (POST-010). Lives here because it calls the AI provider; the
# social module owns the post itself.
posts_router = APIRouter(prefix="/v1/posts", tags=["posts"])


@posts_router.get(
    "/{post_id}/translation", response_model=TranslationOut, openapi_extra=rate_limited("ai")
)
async def translate_post(
    post_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    target: Annotated[str, Query(max_length=35, pattern=r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")],
) -> TranslationOut:
    return await _service(request).translate_post(principal.user_id, post_id, target)
