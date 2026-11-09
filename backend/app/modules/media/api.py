"""``/v1/media``: upload, status polling, finalize (BL-1.08)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import JSONResponse

from app.core.ratelimit import rate_limited
from app.core.security.authn import get_principal
from app.core.security.principal import Principal
from app.modules.media.schemas import CreateMediaUploadRequest, MediaAssetOut
from app.modules.media.service import MediaService

router = APIRouter(prefix="/v1/media", tags=["media"])

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def _service(request: Request) -> MediaService:
    service: MediaService = request.app.state.media_service
    return service


@router.post(
    "/uploads", status_code=status.HTTP_201_CREATED, openapi_extra=rate_limited("media_upload")
)
async def create_upload(
    body: CreateMediaUploadRequest,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
) -> JSONResponse:
    upload, replayed = await _service(request).create_upload(
        principal, body, idempotency_key=idempotency_key
    )
    headers = {"Idempotent-Replayed": "true"} if replayed else {}
    return JSONResponse(
        upload.model_dump(mode="json"), status_code=status.HTTP_201_CREATED, headers=headers
    )


@router.get("/{media_id}", response_model=MediaAssetOut)
async def get_media(
    media_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> MediaAssetOut:
    return await _service(request).get(principal.user_id, media_id)


@router.post(
    "/{media_id}/finalize",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=MediaAssetOut,
    openapi_extra=rate_limited("media_upload"),
)
async def finalize_media(
    media_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> MediaAssetOut:
    return await _service(request).finalize(principal.user_id, media_id)
