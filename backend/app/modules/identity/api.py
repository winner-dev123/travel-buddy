"""HTTP adapters for auth, my sessions, me bootstrap and the development-only IdP."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response, status
from fastapi.responses import JSONResponse

from app.core.ratelimit import rate_limited
from app.core.security.authn import get_principal
from app.core.security.principal import Principal
from app.modules.identity.adapters.dev_idp import DevIdentityProvider
from app.modules.identity.schemas import (
    AccountDeletionRequest,
    AuthResult,
    ConsentList,
    ConsentRecordOut,
    ConsentRequest,
    DataSubjectRequestOut,
    DevIdpToken,
    DevIdpTokenRequest,
    Jwks,
    LoginRequest,
    LogoutRequest,
    Me,
    PushDeviceOut,
    RefreshRequest,
    RegisterPushDeviceRequest,
    RegisterRequest,
    SessionList,
    SessionTokens,
)
from app.modules.identity.service import IdentityService
from app.modules.profiles.schemas import (
    Preferences,
    PrivacySettings,
    UpdateMyProfileRequest,
    UpdatePreferencesRequest,
    UpdatePrivacySettingsRequest,
)

auth_router = APIRouter(prefix="/v1/auth", tags=["auth"])
me_router = APIRouter(prefix="/v1/users/me", tags=["me"])
dev_idp_router = APIRouter(prefix="/v1/dev/idp", tags=["auth"])

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def _service(request: Request) -> IdentityService:
    service: IdentityService = request.app.state.identity_service
    return service


@auth_router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=AuthResult,
    openapi_extra=rate_limited("auth"),
)
async def register(
    body: RegisterRequest,
    request: Request,
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
) -> AuthResult:
    # Replays are naturally safe: (issuer, subject) is unique, so a retry yields 409 and the client
    # logs in; no stored response is needed.
    del idempotency_key
    return await _service(request).register(body, user_agent=request.headers.get("user-agent"))


@auth_router.post("/login", response_model=AuthResult, openapi_extra=rate_limited("auth"))
async def login(body: LoginRequest, request: Request) -> AuthResult:
    return await _service(request).login(body, user_agent=request.headers.get("user-agent"))


@auth_router.post(
    "/refresh",
    response_model=SessionTokens,
    openapi_extra=rate_limited("auth", bucket="auth_refresh"),
)
async def refresh(body: RefreshRequest, request: Request) -> SessionTokens:
    return await _service(request).refresh(body.refresh_token)


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request, principal: CurrentPrincipal, body: LogoutRequest | None = None
) -> Response:
    await _service(request).logout(principal, all_sessions=bool(body and body.all_sessions))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@me_router.get("", response_model=Me)
async def get_me(request: Request, principal: CurrentPrincipal) -> Me:
    return await _service(request).get_me(principal)


@me_router.patch("", response_model=Me)
async def update_me(
    body: UpdateMyProfileRequest, request: Request, principal: CurrentPrincipal
) -> Me:
    return await _service(request).update_me(principal, body)


@me_router.post("/onboarding/complete", response_model=Me)
async def complete_onboarding(request: Request, principal: CurrentPrincipal) -> Me:
    return await _service(request).complete_onboarding(principal)


@me_router.get("/preferences", response_model=Preferences)
async def get_my_preferences(request: Request, principal: CurrentPrincipal) -> Preferences:
    return await _service(request).get_preferences(principal)


@me_router.patch("/preferences", response_model=Preferences)
async def update_my_preferences(
    body: UpdatePreferencesRequest, request: Request, principal: CurrentPrincipal
) -> Preferences:
    return await _service(request).update_preferences(principal, body)


@me_router.get("/privacy", response_model=PrivacySettings)
async def get_my_privacy(request: Request, principal: CurrentPrincipal) -> PrivacySettings:
    return await _service(request).get_privacy(principal)


@me_router.patch("/privacy", response_model=PrivacySettings)
async def update_my_privacy(
    body: UpdatePrivacySettingsRequest, request: Request, principal: CurrentPrincipal
) -> PrivacySettings:
    return await _service(request).update_privacy(principal, body)


@me_router.get("/consents", response_model=ConsentList)
async def list_my_consents(request: Request, principal: CurrentPrincipal) -> ConsentList:
    return await _service(request).list_consents(principal)


@me_router.post("/consents", status_code=status.HTTP_201_CREATED, response_model=ConsentRecordOut)
async def record_my_consent(
    body: ConsentRequest, request: Request, principal: CurrentPrincipal
) -> ConsentRecordOut:
    return await _service(request).record_consent(principal, body)


@me_router.post(
    "/deletion",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=DataSubjectRequestOut,
    openapi_extra=rate_limited("sensitive"),
)
async def request_account_deletion(
    body: AccountDeletionRequest,
    request: Request,
    principal: CurrentPrincipal,
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
) -> JSONResponse:
    record, replayed = await _service(request).request_deletion(
        principal, body, idempotency_key=idempotency_key
    )
    headers = {"Idempotent-Replayed": "true"} if replayed else {}
    return JSONResponse(
        record.model_dump(mode="json"), status_code=status.HTTP_202_ACCEPTED, headers=headers
    )


@me_router.delete("/deletion", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_account_deletion(request: Request, principal: CurrentPrincipal) -> Response:
    await _service(request).cancel_deletion(principal)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@me_router.get("/sessions", response_model=SessionList)
async def list_my_sessions(request: Request, principal: CurrentPrincipal) -> SessionList:
    return await _service(request).list_sessions(principal)


@me_router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_my_session(
    session_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _service(request).revoke_session(principal, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@me_router.post("/devices", status_code=status.HTTP_201_CREATED, response_model=PushDeviceOut)
async def register_push_device(
    body: RegisterPushDeviceRequest, request: Request, principal: CurrentPrincipal
) -> PushDeviceOut:
    return await _service(request).register_push_device(principal, body)


@me_router.delete("/devices/{device_token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_push_device(
    device_token_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _service(request).unregister_push_device(principal, device_token_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _dev_idp(request: Request) -> DevIdentityProvider:
    provider: DevIdentityProvider = request.app.state.dev_idp
    return provider


@dev_idp_router.post("/token", response_model=DevIdpToken, openapi_extra=rate_limited("auth"))
async def dev_idp_mint_token(body: DevIdpTokenRequest, request: Request) -> DevIdpToken:
    token, expires_at = _dev_idp(request).mint(
        sub=body.sub,
        email=body.email,
        email_verified=body.email_verified,
        name=body.name,
        nonce=body.nonce,
        mfa=body.mfa,
    )
    return DevIdpToken(id_token=token, expires_at=expires_at)


@dev_idp_router.get("/jwks.json", response_model=Jwks)
async def dev_idp_jwks(request: Request) -> Jwks:
    return Jwks.model_validate(_dev_idp(request).jwks())
