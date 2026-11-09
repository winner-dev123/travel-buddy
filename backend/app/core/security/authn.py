"""Request authentication: ``Authorization: Bearer <platform access token>`` → Principal."""

from __future__ import annotations

from fastapi import Request

from app.core.errors import AppError, ErrorCode
from app.core.request_context import user_id_var
from app.core.security.access_tokens import AccessTokenService
from app.core.security.principal import AccountStatus, PlatformRole, Principal

_KNOWN_ROLES = {role.value for role in PlatformRole}


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization")
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def _principal_from_token(request: Request, token: str) -> Principal:
    service: AccessTokenService = request.app.state.access_tokens
    claims = service.verify(token)
    principal = Principal(
        user_id=claims.user_id,
        session_id=claims.session_id,
        # Suspension and deletion revoke sessions; access tokens expire within their TTL.
        account_status=AccountStatus.ACTIVE,
        roles=frozenset(PlatformRole(r) for r in claims.roles if r in _KNOWN_ROLES),
        email_verified=claims.email_verified,
        age_assured=claims.age_assured,
        amr=claims.amr,
        auth_time=claims.auth_time,
    )
    user_id_var.set(str(principal.user_id))
    return principal


async def get_principal(request: Request) -> Principal:
    """FastAPI dependency for authenticated routes."""
    token = _bearer_token(request)
    if token is None:
        raise AppError(
            ErrorCode.UNAUTHENTICATED,
            "Sign in to continue.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _principal_from_token(request, token)


async def get_optional_principal(request: Request) -> Principal | None:
    """For routes that also serve guests: no header → None; a bad token is still an error."""
    token = _bearer_token(request)
    if token is None:
        return None
    return _principal_from_token(request, token)
