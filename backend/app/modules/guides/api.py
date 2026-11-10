"""Guides and audio tours: ``/v1/destinations/{id}/guides|audio-tours``, ``/v1/guides/{id}``,
``/v1/audio-tours/{id}`` (BL-4.07)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request

from app.core.i18n import parse_accept_language
from app.core.security.authn import get_optional_principal, get_principal
from app.core.security.principal import Principal
from app.modules.guides.schemas import AudioTour, AudioTourSummaryList, Guide, GuideSummaryList
from app.modules.guides.service import GuideService

router = APIRouter(tags=["guides"])

OptionalPrincipal = Annotated[Principal | None, Depends(get_optional_principal)]
CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
AcceptLanguage = Annotated[str | None, Header(alias="Accept-Language", max_length=200)]


def _service(request: Request) -> GuideService:
    service: GuideService = request.app.state.guide_service
    return service


def _viewer(principal: Principal | None) -> uuid.UUID | None:
    return principal.user_id if principal is not None else None


@router.get("/v1/destinations/{destination_id}/guides", response_model=GuideSummaryList)
async def list_destination_guides(
    destination_id: uuid.UUID,
    request: Request,
    principal: OptionalPrincipal,
    accept_language: AcceptLanguage = None,
) -> GuideSummaryList:
    return await _service(request).list_guides(
        destination_id, _viewer(principal), preferences=parse_accept_language(accept_language)
    )


@router.get("/v1/guides/{guide_id}", response_model=Guide)
async def get_guide(
    guide_id: uuid.UUID,
    request: Request,
    principal: OptionalPrincipal,
    accept_language: AcceptLanguage = None,
) -> Guide:
    return await _service(request).get_guide(
        guide_id, _viewer(principal), preferences=parse_accept_language(accept_language)
    )


@router.get("/v1/destinations/{destination_id}/audio-tours", response_model=AudioTourSummaryList)
async def list_destination_audio_tours(
    destination_id: uuid.UUID,
    request: Request,
    principal: OptionalPrincipal,
    accept_language: AcceptLanguage = None,
) -> AudioTourSummaryList:
    return await _service(request).list_tours(
        destination_id, _viewer(principal), preferences=parse_accept_language(accept_language)
    )


@router.get("/v1/audio-tours/{tour_id}", response_model=AudioTour)
async def get_audio_tour(
    tour_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    accept_language: AcceptLanguage = None,
) -> AudioTour:
    return await _service(request).get_tour(
        tour_id, principal.user_id, preferences=parse_accept_language(accept_language)
    )
