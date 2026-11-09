"""RFC 9457 problem details with stable machine-readable error codes.

Clients switch on ``code``, never on ``title``. See docs/02-system-architecture.md section 5 and
docs/05-rest-api-specification.md for the catalogue.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from enum import StrEnum
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import current_request_id

logger = logging.getLogger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"


class ErrorCode(StrEnum):
    VALIDATION_FAILED = "validation_failed"
    INVALID_CURSOR = "invalid_cursor"
    UNAUTHENTICATED = "unauthenticated"
    MFA_REQUIRED = "mfa_required"
    REAUTHENTICATION_REQUIRED = "reauthentication_required"
    JUSTIFICATION_REQUIRED = "justification_required"
    TOKEN_EXPIRED = "token_expired"  # noqa: S105 - error code, not a secret
    TOKEN_INVALID = "token_invalid"  # noqa: S105 - error code, not a secret
    REFRESH_TOKEN_REUSED = "refresh_token_reused"  # noqa: S105 - error code, not a secret
    SESSION_REVOKED = "session_revoked"
    CONSENT_REQUIRED = "consent_required"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    CONFLICT = "conflict"
    PRECONDITION_FAILED = "precondition_failed"
    IDEMPOTENCY_KEY_REUSED = "idempotency_key_reused"
    IDEMPOTENCY_KEY_IN_PROGRESS = "idempotency_key_in_progress"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXCEEDED = "quota_exceeded"
    ENTITLEMENT_REQUIRED = "entitlement_required"
    FEATURE_DISABLED = "feature_disabled"
    AGE_RESTRICTED = "age_restricted"
    EMAIL_UNVERIFIED = "email_unverified"
    ACCOUNT_SUSPENDED = "account_suspended"
    BLOCKED_RELATIONSHIP = "blocked_relationship"
    CONNECTION_REQUIRED = "connection_required"
    CONNECTION_REQUEST_COOLDOWN = "connection_request_cooldown"
    GROUP_CAPACITY_REACHED = "group_capacity_reached"
    INVITATION_INVALID = "invitation_invalid"
    CHALLENGE_NOT_ACTIVE = "challenge_not_active"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"
    LOCATION_UNRESOLVABLE = "location_unresolvable"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    SERVICE_UNAVAILABLE = "service_unavailable"
    INTERNAL_ERROR = "internal_error"


_DEFAULT_STATUS: Mapping[ErrorCode, HTTPStatus] = {
    ErrorCode.VALIDATION_FAILED: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.INVALID_CURSOR: HTTPStatus.BAD_REQUEST,
    ErrorCode.UNAUTHENTICATED: HTTPStatus.UNAUTHORIZED,
    ErrorCode.MFA_REQUIRED: HTTPStatus.FORBIDDEN,
    ErrorCode.LOCATION_UNRESOLVABLE: HTTPStatus.UNPROCESSABLE_ENTITY,
    ErrorCode.REAUTHENTICATION_REQUIRED: HTTPStatus.UNAUTHORIZED,
    ErrorCode.JUSTIFICATION_REQUIRED: HTTPStatus.BAD_REQUEST,
    ErrorCode.TOKEN_EXPIRED: HTTPStatus.UNAUTHORIZED,
    ErrorCode.TOKEN_INVALID: HTTPStatus.UNAUTHORIZED,
    ErrorCode.REFRESH_TOKEN_REUSED: HTTPStatus.UNAUTHORIZED,
    ErrorCode.SESSION_REVOKED: HTTPStatus.UNAUTHORIZED,
    ErrorCode.CONSENT_REQUIRED: HTTPStatus.FORBIDDEN,
    ErrorCode.FORBIDDEN: HTTPStatus.FORBIDDEN,
    ErrorCode.NOT_FOUND: HTTPStatus.NOT_FOUND,
    ErrorCode.METHOD_NOT_ALLOWED: HTTPStatus.METHOD_NOT_ALLOWED,
    ErrorCode.CONFLICT: HTTPStatus.CONFLICT,
    ErrorCode.PRECONDITION_FAILED: HTTPStatus.PRECONDITION_FAILED,
    ErrorCode.IDEMPOTENCY_KEY_REUSED: HTTPStatus.CONFLICT,
    ErrorCode.IDEMPOTENCY_KEY_IN_PROGRESS: HTTPStatus.CONFLICT,
    ErrorCode.PAYLOAD_TOO_LARGE: HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
    ErrorCode.UNSUPPORTED_MEDIA_TYPE: HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
    ErrorCode.RATE_LIMITED: HTTPStatus.TOO_MANY_REQUESTS,
    ErrorCode.QUOTA_EXCEEDED: HTTPStatus.TOO_MANY_REQUESTS,
    ErrorCode.ENTITLEMENT_REQUIRED: HTTPStatus.FORBIDDEN,
    ErrorCode.FEATURE_DISABLED: HTTPStatus.FORBIDDEN,
    ErrorCode.AGE_RESTRICTED: HTTPStatus.FORBIDDEN,
    ErrorCode.EMAIL_UNVERIFIED: HTTPStatus.FORBIDDEN,
    ErrorCode.ACCOUNT_SUSPENDED: HTTPStatus.FORBIDDEN,
    ErrorCode.BLOCKED_RELATIONSHIP: HTTPStatus.FORBIDDEN,
    ErrorCode.CONNECTION_REQUIRED: HTTPStatus.FORBIDDEN,
    ErrorCode.CONNECTION_REQUEST_COOLDOWN: HTTPStatus.CONFLICT,
    ErrorCode.GROUP_CAPACITY_REACHED: HTTPStatus.CONFLICT,
    ErrorCode.INVITATION_INVALID: HTTPStatus.GONE,
    ErrorCode.CHALLENGE_NOT_ACTIVE: HTTPStatus.CONFLICT,
    ErrorCode.ATTEMPTS_EXHAUSTED: HTTPStatus.TOO_MANY_REQUESTS,
    ErrorCode.UPSTREAM_UNAVAILABLE: HTTPStatus.SERVICE_UNAVAILABLE,
    ErrorCode.SERVICE_UNAVAILABLE: HTTPStatus.SERVICE_UNAVAILABLE,
    ErrorCode.INTERNAL_ERROR: HTTPStatus.INTERNAL_SERVER_ERROR,
}

_STATUS_TO_CODE: Mapping[int, ErrorCode] = {
    400: ErrorCode.VALIDATION_FAILED,
    401: ErrorCode.UNAUTHENTICATED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    409: ErrorCode.CONFLICT,
    412: ErrorCode.PRECONDITION_FAILED,
    413: ErrorCode.PAYLOAD_TOO_LARGE,
    415: ErrorCode.UNSUPPORTED_MEDIA_TYPE,
    422: ErrorCode.VALIDATION_FAILED,
    429: ErrorCode.RATE_LIMITED,
    503: ErrorCode.SERVICE_UNAVAILABLE,
}


class FieldError(BaseModel):
    model_config = ConfigDict(frozen=True)

    field: str
    code: str
    message: str


class Problem(BaseModel):
    """Wire format of ``application/problem+json`` responses."""

    model_config = ConfigDict(extra="allow")

    type: str
    title: str
    status: int
    code: ErrorCode
    detail: str | None = None
    instance: str | None = None
    request_id: str | None = None
    errors: list[FieldError] | None = None


class AppError(Exception):
    """Raise from any layer to produce a problem+json response.

    ``extensions`` become additional top-level members (e.g. ``entitlement``, ``retry_after``).
    Never put secrets or other users' personal data into ``detail`` or ``extensions``.
    """

    def __init__(
        self,
        code: ErrorCode,
        detail: str | None = None,
        *,
        status: int | None = None,
        title: str | None = None,
        errors: Sequence[FieldError] | None = None,
        extensions: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.code = code
        self.status = int(status if status is not None else _DEFAULT_STATUS[code])
        self.title = title or HTTPStatus(self.status).phrase
        self.detail = detail
        self.errors = list(errors) if errors else None
        self.extensions = dict(extensions or {})
        self.headers = dict(headers or {})
        super().__init__(detail or code.value)


def build_problem(
    *,
    type_base_url: str,
    code: ErrorCode,
    status: int,
    title: str,
    detail: str | None = None,
    instance: str | None = None,
    errors: Sequence[FieldError] | None = None,
    extensions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    problem = Problem(
        type=f"{type_base_url}{code.value}",
        title=title,
        status=status,
        code=code,
        detail=detail,
        instance=instance,
        request_id=current_request_id(),
        errors=list(errors) if errors else None,
    )
    body = problem.model_dump(mode="json", exclude_none=True)
    for key, value in (extensions or {}).items():
        if key not in body:  # extensions never override standard members
            body[key] = value
    return body


def _problem_response(
    request: Request,
    *,
    code: ErrorCode,
    status: int,
    title: str,
    detail: str | None = None,
    errors: Sequence[FieldError] | None = None,
    extensions: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    type_base_url: str = request.app.state.settings.error_type_base_url
    body = build_problem(
        type_base_url=type_base_url,
        code=code,
        status=status,
        title=title,
        detail=detail,
        instance=request.url.path,
        errors=errors,
        extensions=extensions,
    )
    return JSONResponse(
        body, status_code=status, media_type=PROBLEM_MEDIA_TYPE, headers=dict(headers or {})
    )


def _field_path(loc: Sequence[int | str]) -> str:
    # Drop the leading location kind ("body", "query", ...) but keep it for non-body sources.
    parts = [str(p) for p in loc]
    if parts and parts[0] == "body":
        parts = parts[1:]
    return ".".join(parts) or "request"


async def _handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return _problem_response(
        request,
        code=exc.code,
        status=exc.status,
        title=exc.title,
        detail=exc.detail,
        errors=exc.errors,
        extensions=exc.extensions,
        headers=exc.headers,
    )


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [
        FieldError(
            field=_field_path(err.get("loc", ())),
            code=str(err.get("type", "invalid")),
            message=str(err.get("msg", "Invalid value")),
        )
        for err in exc.errors()
    ]
    return _problem_response(
        request,
        code=ErrorCode.VALIDATION_FAILED,
        status=HTTPStatus.UNPROCESSABLE_ENTITY,
        title="Validation failed",
        detail="One or more fields are invalid.",
        errors=errors,
    )


async def _handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _STATUS_TO_CODE.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
    detail = exc.detail if isinstance(exc.detail, str) else None
    return _problem_response(
        request,
        code=code,
        status=exc.status_code,
        title=HTTPStatus(exc.status_code).phrase,
        detail=detail,
        headers=exc.headers,
    )


INTERNAL_ERROR_DETAIL = (
    "An unexpected error occurred. Quote the request_id when contacting support."
)


def install_error_handlers(app: FastAPI) -> None:
    """Register handlers for expected errors.

    Unexpected exceptions are deliberately *not* handled here: Starlette runs a catch-all
    ``Exception`` handler in its outermost ServerErrorMiddleware, i.e. outside
    RequestContextMiddleware, so the response would lose the request ID. They are rendered by
    ``RequestContextMiddleware`` instead (see app/core/middleware.py).
    """
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
