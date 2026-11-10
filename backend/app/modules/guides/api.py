"""Guides and audio tours: ``/v1/destinations/{id}/guides|audio-tours``, ``/v1/guides/{id}``,
``/v1/audio-tours/{id}`` (BL-4.07)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse

from app.core.i18n import parse_accept_language
from app.core.security.authn import get_optional_principal, get_principal
from app.core.security.principal import Principal
from app.modules.guides.packages import OfflinePackageService
from app.modules.guides.schemas import (
    AudioTour,
    AudioTourSummaryList,
    Guide,
    GuideSummaryList,
    LicenseRequest,
    OfflineLicenseList,
    OfflinePackageLicenseOut,
    OfflinePackageList,
)
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


# ─────────────────────────────── offline packages (BL-4.08) ───────────────────────────────


def _offline(request: Request) -> OfflinePackageService:
    service: OfflinePackageService = request.app.state.offline_package_service
    return service


@router.get("/v1/destinations/{destination_id}/offline-packages", response_model=OfflinePackageList)
async def list_offline_packages(
    destination_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> OfflinePackageList:
    return await _offline(request).list_for_destination(destination_id, principal.user_id)


@router.post(
    "/v1/offline-packages/{package_id}/licenses",
    status_code=status.HTTP_201_CREATED,
    response_model=OfflinePackageLicenseOut,
)
async def license_offline_package(
    package_id: uuid.UUID, body: LicenseRequest, request: Request, principal: CurrentPrincipal
) -> OfflinePackageLicenseOut:
    return await _offline(request).license(
        principal.user_id,
        package_id,
        body.device_id,
        download_base=f"{str(request.base_url).rstrip('/')}/v1/offline-downloads",
    )


@router.delete(
    "/v1/offline-packages/{package_id}/licenses/{license_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def release_offline_license(
    package_id: uuid.UUID, license_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _offline(request).release(principal.user_id, package_id, license_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/v1/offline-packages/{package_id}/manifest")
async def get_offline_manifest(
    package_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> JSONResponse:
    # Returned verbatim: re-serializing could change the bytes the signature covers.
    return JSONResponse(await _offline(request).manifest(principal.user_id, package_id))


@router.get("/v1/users/me/offline-packages", response_model=OfflineLicenseList)
async def list_my_offline_licenses(
    request: Request, principal: CurrentPrincipal
) -> OfflineLicenseList:
    return await _offline(request).my_licenses(principal.user_id)


@router.get("/v1/offline-downloads/{token}/{file}")
async def download_offline_file(token: str, file: str, request: Request) -> RedirectResponse:
    """The token is the authorization (no bearer: download managers fetch these URLs)."""
    url = await _offline(request).download_url(token, file)
    return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
