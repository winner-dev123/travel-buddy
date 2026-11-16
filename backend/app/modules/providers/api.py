"""``/v1/providers``, ``/v1/provider-offerings``, ``/v1/provider-inquiries``,
``/v1/provider-reviews`` and ``/v1/users/me/providers|inquiries`` (ADR-0036, docs/18 §4)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.feature_flags import Flag, gate
from app.core.i18n import parse_accept_language
from app.core.ratelimit import rate_limited
from app.core.security.authn import get_optional_principal, get_principal
from app.core.security.principal import Principal
from app.modules.providers.domain import InquiryAction
from app.modules.providers.schemas import (
    AddDocumentRequest,
    ChangeMemberRoleRequest,
    CreateInquiryRequest,
    CreateOfferingRequest,
    CreateProviderRequest,
    CreateReviewRequest,
    DeclineInquiryRequest,
    DocumentList,
    DocumentOut,
    InquiryOut,
    InquiryPage,
    InquiryStatusName,
    InviteMemberRequest,
    KindName,
    MemberList,
    OfferingOut,
    OfferingPage,
    ProviderMembershipList,
    ProviderPage,
    ProviderProfile,
    ProviderWorkspace,
    ReplyReviewRequest,
    ReviewOut,
    ReviewPage,
    ServiceAreasRequest,
    SpecialtyName,
    SubmitProviderRequest,
    UpdateOfferingRequest,
    UpdateProviderRequest,
)
from app.modules.providers.service import ProviderService

router = APIRouter(tags=["providers"], dependencies=gate(Flag.PROVIDER_MARKETPLACE))

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
OptionalPrincipal = Annotated[Principal | None, Depends(get_optional_principal)]
AcceptLanguage = Annotated[str | None, Header(alias="Accept-Language", max_length=200)]
IfMatch = Annotated[str | None, Header(alias="If-Match", max_length=40)]
IdempotencyKey = Annotated[uuid.UUID, Header(alias="Idempotency-Key")]
Cursor = Annotated[str | None, Query(max_length=1024)]
Limit = Annotated[int, Query(ge=1, le=50)]


def _service(request: Request) -> ProviderService:
    service: ProviderService = request.app.state.provider_service
    return service


def _viewer(principal: Principal | None) -> uuid.UUID | None:
    return principal.user_id if principal is not None else None


def _tagged(model: BaseModel, version: int, *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        model.model_dump(mode="json"), status_code=status_code, headers={"ETag": f'"{version}"'}
    )


def _workspace(out: ProviderWorkspace, *, status_code: int = 200) -> JSONResponse:
    return _tagged(out, out.version, status_code=status_code)


# ───────────────────────────── browsing (PROV-007) ─────────────────────────────


@router.get("/v1/providers", response_model=ProviderPage)
async def list_providers(
    request: Request,
    principal: OptionalPrincipal,
    destination_id: uuid.UUID | None = None,
    kind: KindName | None = None,
    language: Annotated[str | None, Query(pattern=r"^[a-z]{2,3}(-[A-Z]{2})?$")] = None,
    specialty: SpecialtyName | None = None,
    cursor: Cursor = None,
    limit: Limit = 20,
    accept_language: AcceptLanguage = None,
) -> ProviderPage:
    return await _service(request).list_providers(
        _viewer(principal),
        destination_id=destination_id,
        kind=kind,
        language=language,
        specialty=specialty,
        cursor=cursor,
        limit=limit,
        prefs=parse_accept_language(accept_language),
    )


@router.get("/v1/providers/{provider_id}", response_model=ProviderProfile)
async def get_provider(
    provider_id: uuid.UUID,
    request: Request,
    principal: OptionalPrincipal,
    accept_language: AcceptLanguage = None,
) -> ProviderProfile:
    return await _service(request).get_profile(
        _viewer(principal), provider_id, parse_accept_language(accept_language)
    )


@router.get("/v1/providers/{provider_id}/offerings", response_model=OfferingPage)
async def list_provider_offerings(
    provider_id: uuid.UUID,
    request: Request,
    principal: OptionalPrincipal,
    status_filter: Annotated[Literal["published", "all"], Query(alias="status")] = "published",
    cursor: Cursor = None,
    limit: Limit = 20,
    accept_language: AcceptLanguage = None,
) -> OfferingPage:
    return await _service(request).list_offerings(
        _viewer(principal),
        provider_id,
        include_all=status_filter == "all",
        cursor=cursor,
        limit=limit,
        prefs=parse_accept_language(accept_language),
    )


@router.get("/v1/providers/{provider_id}/reviews", response_model=ReviewPage)
async def list_provider_reviews(
    provider_id: uuid.UUID,
    request: Request,
    principal: OptionalPrincipal,
    cursor: Cursor = None,
    limit: Limit = 20,
) -> ReviewPage:
    return await _service(request).list_reviews(
        _viewer(principal), provider_id, cursor=cursor, limit=limit
    )


@router.get("/v1/provider-offerings/{offering_id}", response_model=OfferingOut)
async def get_offering(
    offering_id: uuid.UUID,
    request: Request,
    principal: OptionalPrincipal,
    accept_language: AcceptLanguage = None,
) -> OfferingOut:
    return await _service(request).get_offering(
        _viewer(principal), offering_id, parse_accept_language(accept_language)
    )


# ───────────────────────────── applying (PROV-001..004) ─────────────────────────────


@router.get("/v1/users/me/providers", response_model=ProviderMembershipList)
async def my_providers(
    request: Request, principal: CurrentPrincipal, accept_language: AcceptLanguage = None
) -> ProviderMembershipList:
    return await _service(request).my_providers(
        principal.user_id, parse_accept_language(accept_language)
    )


@router.post("/v1/providers", status_code=status.HTTP_201_CREATED, response_model=ProviderWorkspace)
async def create_provider(
    body: CreateProviderRequest,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKey,
    accept_language: AcceptLanguage = None,
) -> JSONResponse:
    out = await _service(request).create(
        principal,
        body,
        idempotency_key=idempotency_key,
        prefs=parse_accept_language(accept_language),
    )
    response = _workspace(out, status_code=status.HTTP_201_CREATED)
    response.headers["Location"] = f"/v1/providers/{out.id}"
    return response


@router.get("/v1/providers/{provider_id}/workspace", response_model=ProviderWorkspace)
async def get_workspace(
    provider_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    accept_language: AcceptLanguage = None,
) -> JSONResponse:
    return _workspace(
        await _service(request).workspace(
            principal.user_id, provider_id, parse_accept_language(accept_language)
        )
    )


@router.patch("/v1/providers/{provider_id}", response_model=ProviderWorkspace)
async def update_provider(
    provider_id: uuid.UUID,
    body: UpdateProviderRequest,
    request: Request,
    principal: CurrentPrincipal,
    if_match: IfMatch = None,
    accept_language: AcceptLanguage = None,
) -> JSONResponse:
    return _workspace(
        await _service(request).update(
            principal.user_id,
            provider_id,
            body,
            if_match=if_match,
            prefs=parse_accept_language(accept_language),
        )
    )


@router.put("/v1/providers/{provider_id}/service-areas", response_model=ProviderWorkspace)
async def set_service_areas(
    provider_id: uuid.UUID,
    body: ServiceAreasRequest,
    request: Request,
    principal: CurrentPrincipal,
    accept_language: AcceptLanguage = None,
) -> JSONResponse:
    return _workspace(
        await _service(request).set_service_areas(
            principal.user_id, provider_id, body, parse_accept_language(accept_language)
        )
    )


@router.get("/v1/providers/{provider_id}/documents", response_model=DocumentList)
async def list_documents(
    provider_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> DocumentList:
    return await _service(request).list_documents(principal.user_id, provider_id)


@router.post(
    "/v1/providers/{provider_id}/documents",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentOut,
    openapi_extra=rate_limited("sensitive"),
)
async def add_document(
    provider_id: uuid.UUID, body: AddDocumentRequest, request: Request, principal: CurrentPrincipal
) -> DocumentOut:
    return await _service(request).add_document(principal.user_id, provider_id, body)


@router.delete(
    "/v1/providers/{provider_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document(
    provider_id: uuid.UUID, document_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _service(request).delete_document(principal.user_id, provider_id, document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/v1/providers/{provider_id}/submit", response_model=ProviderWorkspace)
async def submit_provider(
    provider_id: uuid.UUID,
    body: SubmitProviderRequest,
    request: Request,
    principal: CurrentPrincipal,
    accept_language: AcceptLanguage = None,
) -> JSONResponse:
    return _workspace(
        await _service(request).submit(
            principal.user_id, provider_id, body, parse_accept_language(accept_language)
        )
    )


@router.post("/v1/providers/{provider_id}/deactivate", response_model=ProviderWorkspace)
async def deactivate_provider(
    provider_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    accept_language: AcceptLanguage = None,
) -> JSONResponse:
    return _workspace(
        await _service(request).deactivate(
            principal.user_id, provider_id, parse_accept_language(accept_language)
        )
    )


# ───────────────────────────── team (PROV-005) ─────────────────────────────


@router.get("/v1/providers/{provider_id}/members", response_model=MemberList)
async def list_members(
    provider_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> MemberList:
    return await _service(request).list_members(principal.user_id, provider_id)


@router.post(
    "/v1/providers/{provider_id}/members",
    status_code=status.HTTP_201_CREATED,
    response_model=MemberList,
    openapi_extra=rate_limited("sensitive", bucket="invitation"),
)
async def invite_member(
    provider_id: uuid.UUID, body: InviteMemberRequest, request: Request, principal: CurrentPrincipal
) -> MemberList:
    return await _service(request).invite_member(principal.user_id, provider_id, body)


@router.post("/v1/providers/{provider_id}/members/me/accept", response_model=ProviderWorkspace)
async def accept_invitation(
    provider_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    accept_language: AcceptLanguage = None,
) -> JSONResponse:
    return _workspace(
        await _service(request).accept_invitation(
            principal.user_id, provider_id, parse_accept_language(accept_language)
        )
    )


@router.patch("/v1/providers/{provider_id}/members/{user_id}", response_model=MemberList)
async def change_member_role(
    provider_id: uuid.UUID,
    user_id: uuid.UUID,
    body: ChangeMemberRoleRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> MemberList:
    return await _service(request).change_role(principal.user_id, provider_id, user_id, body)


@router.delete(
    "/v1/providers/{provider_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_member(
    provider_id: uuid.UUID, user_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _service(request).remove_member(principal.user_id, provider_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ───────────────────────────── offerings (PROV-006) ─────────────────────────────


@router.post(
    "/v1/providers/{provider_id}/offerings",
    status_code=status.HTTP_201_CREATED,
    response_model=OfferingOut,
)
async def create_offering(
    provider_id: uuid.UUID,
    body: CreateOfferingRequest,
    request: Request,
    principal: CurrentPrincipal,
    accept_language: AcceptLanguage = None,
) -> JSONResponse:
    out = await _service(request).create_offering(
        principal.user_id, provider_id, body, parse_accept_language(accept_language)
    )
    return _tagged(out, out.version, status_code=status.HTTP_201_CREATED)


@router.patch("/v1/provider-offerings/{offering_id}", response_model=OfferingOut)
async def update_offering(
    offering_id: uuid.UUID,
    body: UpdateOfferingRequest,
    request: Request,
    principal: CurrentPrincipal,
    if_match: IfMatch = None,
    accept_language: AcceptLanguage = None,
) -> JSONResponse:
    out = await _service(request).update_offering(
        principal.user_id,
        offering_id,
        body,
        if_match=if_match,
        prefs=parse_accept_language(accept_language),
    )
    return _tagged(out, out.version)


@router.post("/v1/provider-offerings/{offering_id}/publish", response_model=OfferingOut)
async def publish_offering(
    offering_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    accept_language: AcceptLanguage = None,
) -> JSONResponse:
    out = await _service(request).publish_offering(
        principal.user_id, offering_id, parse_accept_language(accept_language)
    )
    return _tagged(out, out.version)


@router.post("/v1/provider-offerings/{offering_id}/archive", response_model=OfferingOut)
async def archive_offering(
    offering_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    accept_language: AcceptLanguage = None,
) -> JSONResponse:
    out = await _service(request).archive_offering(
        principal.user_id, offering_id, parse_accept_language(accept_language)
    )
    return _tagged(out, out.version)


# ───────────────────────────── requests (PROV-009, PROV-010) ─────────────────────────────


@router.post(
    "/v1/providers/{provider_id}/inquiries",
    status_code=status.HTTP_201_CREATED,
    response_model=InquiryOut,
    openapi_extra=rate_limited("contact", bucket="provider_inquiries"),
)
async def create_inquiry(
    provider_id: uuid.UUID,
    body: CreateInquiryRequest,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: IdempotencyKey,
    accept_language: AcceptLanguage = None,
) -> JSONResponse:
    out = await _service(request).create_inquiry(
        principal,
        provider_id,
        body,
        idempotency_key=idempotency_key,
        prefs=parse_accept_language(accept_language),
    )
    response = _tagged(out, out.version, status_code=status.HTTP_201_CREATED)
    response.headers["Location"] = f"/v1/provider-inquiries/{out.id}"
    return response


@router.get("/v1/users/me/inquiries", response_model=InquiryPage)
async def my_inquiries(
    request: Request,
    principal: CurrentPrincipal,
    status_filter: Annotated[InquiryStatusName | None, Query(alias="status")] = None,
    cursor: Cursor = None,
    limit: Limit = 20,
    accept_language: AcceptLanguage = None,
) -> InquiryPage:
    return await _service(request).my_inquiries(
        principal.user_id,
        status=status_filter,
        cursor=cursor,
        limit=limit,
        prefs=parse_accept_language(accept_language),
    )


@router.get("/v1/providers/{provider_id}/inquiries", response_model=InquiryPage)
async def provider_inquiries(
    provider_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    status_filter: Annotated[InquiryStatusName | None, Query(alias="status")] = None,
    cursor: Cursor = None,
    limit: Limit = 20,
    accept_language: AcceptLanguage = None,
) -> InquiryPage:
    return await _service(request).provider_inquiries(
        principal.user_id,
        provider_id,
        status=status_filter,
        cursor=cursor,
        limit=limit,
        prefs=parse_accept_language(accept_language),
    )


@router.get("/v1/provider-inquiries/{inquiry_id}", response_model=InquiryOut)
async def get_inquiry(
    inquiry_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    accept_language: AcceptLanguage = None,
) -> JSONResponse:
    out = await _service(request).get_inquiry(
        principal.user_id, inquiry_id, parse_accept_language(accept_language)
    )
    return _tagged(out, out.version)


async def _transition(
    request: Request,
    principal: Principal,
    inquiry_id: uuid.UUID,
    action: InquiryAction,
    if_match: str | None,
    accept_language: str | None,
    reason: str | None = None,
) -> JSONResponse:
    out = await _service(request).transition(
        principal.user_id,
        inquiry_id,
        action,
        reason=reason,
        if_match=if_match,
        prefs=parse_accept_language(accept_language),
    )
    return _tagged(out, out.version)


@router.post("/v1/provider-inquiries/{inquiry_id}/accept", response_model=InquiryOut)
async def accept_inquiry(
    inquiry_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    if_match: IfMatch = None,
    accept_language: AcceptLanguage = None,
) -> JSONResponse:
    return await _transition(
        request, principal, inquiry_id, InquiryAction.ACCEPT, if_match, accept_language
    )


@router.post("/v1/provider-inquiries/{inquiry_id}/decline", response_model=InquiryOut)
async def decline_inquiry(
    inquiry_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    body: DeclineInquiryRequest | None = None,
    if_match: IfMatch = None,
    accept_language: AcceptLanguage = None,
) -> JSONResponse:
    return await _transition(
        request,
        principal,
        inquiry_id,
        InquiryAction.DECLINE,
        if_match,
        accept_language,
        reason=body.reason if body else None,
    )


@router.post("/v1/provider-inquiries/{inquiry_id}/complete", response_model=InquiryOut)
async def complete_inquiry(
    inquiry_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    if_match: IfMatch = None,
    accept_language: AcceptLanguage = None,
) -> JSONResponse:
    return await _transition(
        request, principal, inquiry_id, InquiryAction.COMPLETE, if_match, accept_language
    )


@router.post("/v1/provider-inquiries/{inquiry_id}/cancel", response_model=InquiryOut)
async def cancel_inquiry(
    inquiry_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    if_match: IfMatch = None,
    accept_language: AcceptLanguage = None,
) -> JSONResponse:
    return await _transition(
        request, principal, inquiry_id, InquiryAction.CANCEL, if_match, accept_language
    )


@router.post("/v1/provider-inquiries/{inquiry_id}/withdraw", response_model=InquiryOut)
async def withdraw_inquiry(
    inquiry_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    if_match: IfMatch = None,
    accept_language: AcceptLanguage = None,
) -> JSONResponse:
    return await _transition(
        request, principal, inquiry_id, InquiryAction.WITHDRAW, if_match, accept_language
    )


# ───────────────────────────── reviews (PROV-011) ─────────────────────────────


@router.post(
    "/v1/provider-inquiries/{inquiry_id}/review",
    status_code=status.HTTP_201_CREATED,
    response_model=ReviewOut,
)
async def create_review(
    inquiry_id: uuid.UUID, body: CreateReviewRequest, request: Request, principal: CurrentPrincipal
) -> ReviewOut:
    return await _service(request).create_review(principal.user_id, inquiry_id, body)


@router.post("/v1/provider-reviews/{review_id}/reply", response_model=ReviewOut)
async def reply_review(
    review_id: uuid.UUID, body: ReplyReviewRequest, request: Request, principal: CurrentPrincipal
) -> ReviewOut:
    return await _service(request).reply_review(principal.user_id, review_id, body)


@router.delete("/v1/provider-reviews/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review(
    review_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _service(request).delete_review(principal.user_id, review_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ───────────────────────────── blocks (PROV-012) ─────────────────────────────


@router.put("/v1/providers/{provider_id}/block", status_code=status.HTTP_204_NO_CONTENT)
async def block_provider(
    provider_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _service(request).block_provider(principal.user_id, provider_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/v1/providers/{provider_id}/block", status_code=status.HTTP_204_NO_CONTENT)
async def unblock_provider(
    provider_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _service(request).unblock_provider(principal.user_id, provider_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/v1/providers/{provider_id}/blocked-travelers/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def block_traveler(
    provider_id: uuid.UUID, user_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _service(request).block_traveler(principal.user_id, provider_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/v1/providers/{provider_id}/blocked-travelers/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unblock_traveler(
    provider_id: uuid.UUID, user_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _service(request).unblock_traveler(principal.user_id, provider_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
