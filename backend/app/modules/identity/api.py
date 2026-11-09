"""HTTP adapters for auth, my sessions, me bootstrap and the development-only IdP."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response, status

from app.core.security.authn import get_principal
from app.core.security.principal import Principal
from app.modules.identity.adapters.dev_idp import DevIdentityProvider
from app.modules.identity.schemas import (
    AuthResult,
    DevIdpToken,
    DevIdpTokenRequest,
    Jwks,
    LoginRequest,
    LogoutRequest,
    Me,
    RefreshRequest,
    RegisterRequest,
    SessionList,
    SessionTokens,
)
from app.modules.identity.service import IdentityService

auth_router = APIRouter(prefix="/v1/auth", tags=["auth"])
me_router = APIRouter(prefix="/v1/users/me", tags=["me"])
dev_idp_router = APIRouter(prefix="/v1/dev/idp", tags=["auth"])

CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def _service(request: Request) -> IdentityService:
    service: IdentityService = request.app.state.identity_service
    return service


@auth_router.post("/register", status_code=status.HTTP_201_CREATED, response_model=AuthResult)
async def register(
    body: RegisterRequest,
    request: Request,
    idempotency_key: Annotated[uuid.UUID, Header(alias="Idempotency-Key")],
) -> AuthResult:
    # Replays are naturally safe: (issuer, subject) is unique, so a retry yields 409 and the client
    # logs in. Stored-response idempotency for all creating POSTs lands with BL-1.15.
    del idempotency_key
    return await _service(request).register(body, user_agent=request.headers.get("user-agent"))


@auth_router.post("/login", response_model=AuthResult)
async def login(body: LoginRequest, request: Request) -> AuthResult:
    return await _service(request).login(body, user_agent=request.headers.get("user-agent"))


@auth_router.post("/refresh", response_model=SessionTokens)
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


@me_router.get("/sessions", response_model=SessionList)
async def list_my_sessions(request: Request, principal: CurrentPrincipal) -> SessionList:
    return await _service(request).list_sessions(principal)


@me_router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_my_session(
    session_id: uuid.UUID, request: Request, principal: CurrentPrincipal
) -> Response:
    await _service(request).revoke_session(principal, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _dev_idp(request: Request) -> DevIdentityProvider:
    provider: DevIdentityProvider = request.app.state.dev_idp
    return provider


@dev_idp_router.post("/token", response_model=DevIdpToken)
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
