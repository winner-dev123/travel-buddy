"""HTTP adapters for ``/v1/users/me/browse-destination`` and ``/upcoming-destinations``."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response, status

from app.core.i18n import parse_accept_language
from app.core.security.authn import get_principal
from app.core.security.principal import Principal
from app.modules.location.schemas import (
    BrowseDestination,
    CreateUpcomingDestinationRequest,
    DiscoverySessionOut,
    SetBrowseDestinationRequest,
    SetDiscoverySessionRequest,
    UpcomingDestination,
    UpcomingDestinationList,
)
from app.modules.location.service import DiscoverySessionService, LocationService

router = APIRouter(prefix="/v1/users/me", tags=["location"])

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
AcceptLanguage = Annotated[str | None, Header(alias="Accept-Language", max_length=200)]


def _service(request: Request) -> LocationService:
    service: LocationService = request.app.state.location_service
    return service


@router.get("/browse-destination", response_model=BrowseDestination)
async def get_browse_destination(
    request: Request, principal: CurrentPrincipal, accept_language: AcceptLanguage = None
) -> BrowseDestination:
    return await _service(request).get_browse(
        principal.user_id, preferences=parse_accept_language(accept_language)
    )


@router.put("/browse-destination", response_model=BrowseDestination)
async def set_browse_destination(
    body: SetBrowseDestinationRequest,
    request: Request,
    principal: CurrentPrincipal,
    accept_language: AcceptLanguage = None,
) -> BrowseDestination:
    return await _service(request).set_browse(
        principal.user_id, body.destination_id, preferences=parse_accept_language(accept_language)
    )


@router.delete("/browse-destination", status_code=status.HTTP_204_NO_CONTENT)
async def clear_browse_destination(request: Request, principal: CurrentPrincipal) -> Response:
    await _service(request).clear_browse(principal.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/upcoming-destinations", response_model=UpcomingDestinationList)
async def list_upcoming_destinations(
    request: Request, principal: CurrentPrincipal, accept_language: AcceptLanguage = None
) -> UpcomingDestinationList:
    return await _service(request).list_upcoming(
        principal.user_id, preferences=parse_accept_language(accept_language)
    )


@router.post(
    "/upcoming-destinations",
    status_code=status.HTTP_201_CREATED,
    response_model=UpcomingDestination,
)
async def add_upcoming_destination(
    body: CreateUpcomingDestinationRequest,
    request: Request,
    principal: CurrentPrincipal,
    accept_language: AcceptLanguage = None,
) -> UpcomingDestination:
    return await _service(request).add_upcoming(
        principal.user_id, body, preferences=parse_accept_language(accept_language)
    )


@router.delete("/upcoming-destinations/{selection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_upcoming_destination(
    selection_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _service(request).remove_upcoming(principal.user_id, selection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _discovery(request: Request) -> DiscoverySessionService:
    service: DiscoverySessionService = request.app.state.discovery_session_service
    return service


@router.get("/discovery-location", response_model=DiscoverySessionOut)
async def get_discovery_location(
    request: Request, principal: CurrentPrincipal, accept_language: AcceptLanguage = None
) -> DiscoverySessionOut:
    return await _discovery(request).get(
        principal.user_id, preferences=parse_accept_language(accept_language)
    )


@router.put("/discovery-location", response_model=DiscoverySessionOut)
async def set_discovery_location(
    body: SetDiscoverySessionRequest,
    request: Request,
    principal: CurrentPrincipal,
    accept_language: AcceptLanguage = None,
) -> DiscoverySessionOut:
    return await _discovery(request).start(
        principal.user_id, body, preferences=parse_accept_language(accept_language)
    )


@router.delete("/discovery-location", status_code=status.HTTP_204_NO_CONTENT)
async def end_discovery_location(request: Request, principal: CurrentPrincipal) -> Response:
    await _discovery(request).end(principal.user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
