"""``/v1/groups`` and ``/v1/group-invitations`` (BL-3.07..3.10)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, Header, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import Field

from app.core.feature_flags import Flag, require_flag
from app.core.ratelimit import rate_limited
from app.core.security.authn import get_principal
from app.core.security.principal import Principal
from app.modules.groups.schemas import (
    AnnouncementRequest,
    ChangeRoleRequest,
    CreatedGroupInvitation,
    CreateGroupRequest,
    CreateTransferRequest,
    DirectInvitationRequest,
    GroupInvitationPage,
    GroupInvitationPreview,
    GroupJoinRequestOut,
    GroupJoinRequestPage,
    GroupMemberOut,
    GroupMemberPage,
    GroupOut,
    GroupPage,
    GroupRoleList,
    GroupSettingsOut,
    InvitationTokenRequest,
    JoinRequestBody,
    LinkInvitationRequest,
    OwnershipTransferOut,
    RestrictMemberRequest,
    RoleKey,
    UpdateGroupRequest,
    UpdateGroupSettingsRequest,
)
from app.modules.groups.service import GroupService

router = APIRouter(prefix="/v1/groups", tags=["groups"])
invitations_router = APIRouter(tags=["groups"])

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
IfMatch = Annotated[str | None, Header(alias="If-Match")]
InvitationBody = Annotated[
    DirectInvitationRequest | LinkInvitationRequest, Field(discriminator="kind")
]


def _service(request: Request) -> GroupService:
    service: GroupService = request.app.state.group_service
    return service


def _tagged(model: GroupOut | GroupSettingsOut, *, status_code: int = 200) -> JSONResponse:
    return JSONResponse(
        model.model_dump(mode="json"),
        status_code=status_code,
        headers={"ETag": f'"{model.version}"'},
    )


@router.get("", response_model=GroupPage)
async def list_my_groups(
    request: Request,
    principal: CurrentPrincipal,
    role: RoleKey | None = None,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> GroupPage:
    return await _service(request).list_mine(
        principal.user_id, role=role, cursor=cursor, limit=limit
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=GroupOut)
async def create_group(
    body: CreateGroupRequest,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
) -> JSONResponse:
    out = await _service(request).create(principal, body, idempotency_key=idempotency_key)
    response = _tagged(out, status_code=status.HTTP_201_CREATED)
    response.headers["Location"] = f"/v1/groups/{out.id}"
    return response


@router.get("/{group_id}", response_model=GroupOut)
async def get_group(
    group_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> JSONResponse:
    return _tagged(await _service(request).get(principal.user_id, group_id))


@router.patch("/{group_id}", response_model=GroupOut)
async def update_group(
    group_id: uuid.UUID,
    body: UpdateGroupRequest,
    request: Request,
    principal: CurrentPrincipal,
    if_match: IfMatch = None,
) -> JSONResponse:
    return _tagged(
        await _service(request).update(principal.user_id, group_id, body, if_match=if_match)
    )


@router.post("/{group_id}/archive", response_model=GroupOut)
async def archive_group(
    group_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> JSONResponse:
    return _tagged(await _service(request).archive(principal.user_id, group_id))


@router.get("/{group_id}/settings", response_model=GroupSettingsOut)
async def get_group_settings(
    group_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> JSONResponse:
    return _tagged(await _service(request).get_settings(principal.user_id, group_id))


@router.patch("/{group_id}/settings", response_model=GroupSettingsOut)
async def update_group_settings(
    group_id: uuid.UUID,
    body: UpdateGroupSettingsRequest,
    request: Request,
    principal: CurrentPrincipal,
    if_match: IfMatch = None,
) -> JSONResponse:
    return _tagged(
        await _service(request).update_settings(
            principal.user_id, group_id, body, if_match=if_match
        )
    )


@router.get("/{group_id}/roles", response_model=GroupRoleList)
async def list_group_roles(
    group_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> GroupRoleList:
    await _service(request).check_member(principal.user_id, group_id)
    return GroupService.roles()


@router.get("/{group_id}/members", response_model=GroupMemberPage)
async def list_group_members(
    group_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    status_filter: Annotated[
        Literal["active", "restricted", "removed", "left"] | None, Query(alias="status")
    ] = None,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> GroupMemberPage:
    return await _service(request).members(
        principal.user_id, group_id, status=status_filter, cursor=cursor, limit=limit
    )


@router.patch("/{group_id}/members/{user_id}", response_model=GroupMemberOut)
async def change_group_member_role(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    body: ChangeRoleRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> GroupMemberOut:
    return await _service(request).change_role(principal.user_id, group_id, user_id, body.role)


@router.delete("/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_group_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    reason_code: Annotated[str | None, Query(max_length=40)] = None,
) -> Response:
    await _service(request).remove_member(principal.user_id, group_id, user_id, reason=reason_code)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{group_id}/members/{user_id}/restriction", response_model=GroupMemberOut)
async def restrict_group_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    body: RestrictMemberRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> GroupMemberOut | None:
    return await _service(request).restrict(
        principal.user_id, group_id, user_id, until=body.until, reason=body.reason_code
    )


@router.delete("/{group_id}/members/{user_id}/restriction", status_code=status.HTTP_204_NO_CONTENT)
async def lift_group_member_restriction(
    group_id: uuid.UUID, user_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _service(request).restrict(principal.user_id, group_id, user_id, until=None, reason=None)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{group_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_group(
    group_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _service(request).leave(principal.user_id, group_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{group_id}/invitations", response_model=GroupInvitationPage)
async def list_group_invitations(
    group_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> GroupInvitationPage:
    return await _service(request).group_invitations(
        principal.user_id, group_id, cursor=cursor, limit=limit
    )


@router.post(
    "/{group_id}/invitations",
    status_code=status.HTTP_201_CREATED,
    response_model=CreatedGroupInvitation,
    openapi_extra=rate_limited("contact"),
)
async def create_group_invitation(
    group_id: uuid.UUID,
    body: Annotated[InvitationBody, Body()],
    request: Request,
    principal: CurrentPrincipal,
) -> JSONResponse:
    out = await _service(request).invite(principal.user_id, group_id, body)
    return JSONResponse(
        out.model_dump(mode="json"),
        status_code=status.HTTP_201_CREATED,
        headers={"Cache-Control": "no-store"},  # the token is shown exactly once
    )


@router.delete("/{group_id}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_group_invitation(
    group_id: uuid.UUID, invitation_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _service(request).revoke_invitation(principal.user_id, group_id, invitation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{group_id}/ownership-transfers",
    status_code=status.HTTP_201_CREATED,
    response_model=OwnershipTransferOut,
)
async def offer_ownership_transfer(
    group_id: uuid.UUID, body: CreateTransferRequest, request: Request, principal: CurrentPrincipal
) -> OwnershipTransferOut:
    return await _service(request).offer_transfer(principal.user_id, group_id, body.to_user_id)


@router.post(
    "/{group_id}/ownership-transfers/{transfer_id}/{action}",
    response_model=OwnershipTransferOut,
)
async def answer_ownership_transfer(
    group_id: uuid.UUID,
    transfer_id: uuid.UUID,
    action: Literal["accept", "decline", "cancel"],
    request: Request,
    principal: CurrentPrincipal,
) -> OwnershipTransferOut:
    return await _service(request).answer_transfer(principal.user_id, group_id, transfer_id, action)


@router.post(
    "/{group_id}/announcements",
    status_code=status.HTTP_201_CREATED,
    openapi_extra=rate_limited("message"),
)
async def post_announcement(
    group_id: uuid.UUID,
    body: AnnouncementRequest,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
) -> JSONResponse:
    del idempotency_key  # deduplicated on client_message_id, like every message
    message = await _service(request).announce(
        principal,
        group_id,
        client_message_id=body.client_message_id,
        body=body.body,
        pin=body.pin,
    )
    return JSONResponse(message, status_code=status.HTTP_201_CREATED)


@invitations_router.get("/v1/users/me/group-invitations", response_model=GroupInvitationPage)
async def list_my_group_invitations(
    request: Request,
    principal: CurrentPrincipal,
    cursor: Annotated[str | None, Query(max_length=1024)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> GroupInvitationPage:
    return await _service(request).my_invitations(principal.user_id, cursor=cursor, limit=limit)


@invitations_router.post(
    "/v1/group-invitations/{invitation_id}/accept", response_model=GroupMemberOut
)
async def accept_group_invitation(
    invitation_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> GroupMemberOut | None:
    return await _service(request).respond(principal.user_id, invitation_id, accept=True)


@invitations_router.post(
    "/v1/group-invitations/{invitation_id}/decline", status_code=status.HTTP_204_NO_CONTENT
)
async def decline_group_invitation(
    invitation_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _service(request).respond(principal.user_id, invitation_id, accept=False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@invitations_router.post(
    "/v1/group-invitations/preview",
    response_model=GroupInvitationPreview,
    openapi_extra=rate_limited("sensitive"),
)
async def preview_group_invitation(
    body: InvitationTokenRequest, request: Request, principal: CurrentPrincipal
) -> GroupInvitationPreview:
    return await _service(request).preview(principal.user_id, body.token)


@invitations_router.post(
    "/v1/group-invitations/redeem",
    response_model=GroupMemberOut,
    openapi_extra=rate_limited("sensitive"),
)
async def redeem_group_invitation(
    body: InvitationTokenRequest, request: Request, principal: CurrentPrincipal
) -> GroupMemberOut:
    return await _service(request).redeem(principal.user_id, body.token)


# Join requests (GRP-006) wait for public groups: behind the ``group_join_requests`` flag.
_JOIN_REQUESTS = [Depends(require_flag(Flag.GROUP_JOIN_REQUESTS))]


@router.get(
    "/{group_id}/join-requests", response_model=GroupJoinRequestPage, dependencies=_JOIN_REQUESTS
)
async def list_group_join_requests(
    group_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> GroupJoinRequestPage:
    return await _service(request).join_requests(principal.user_id, group_id)


@router.post(
    "/{group_id}/join-requests",
    status_code=status.HTTP_201_CREATED,
    response_model=GroupJoinRequestOut,
    dependencies=_JOIN_REQUESTS,
    openapi_extra=rate_limited("contact"),
)
async def create_group_join_request(
    group_id: uuid.UUID,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
    body: JoinRequestBody | None = None,
) -> GroupJoinRequestOut:
    return await _service(request).request_to_join(principal.user_id, group_id)


@router.post(
    "/{group_id}/join-requests/{join_request_id}/approve",
    response_model=GroupMemberOut,
    dependencies=_JOIN_REQUESTS,
)
async def approve_group_join_request(
    group_id: uuid.UUID, join_request_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> GroupMemberOut:
    return await _service(request).review_join_request(principal.user_id, group_id, join_request_id)


@router.post(
    "/{group_id}/join-requests/{join_request_id}/reject",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=_JOIN_REQUESTS,
)
async def reject_group_join_request(
    group_id: uuid.UUID, join_request_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    return await _service(request).review_join_request(principal.user_id, group_id, join_request_id)
