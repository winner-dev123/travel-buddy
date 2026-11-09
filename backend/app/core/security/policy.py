"""Policy decisions: authorization functions return ``Allow | Deny`` instead of raising.

Returning a value keeps domain policies pure and makes denials testable and auditable. The API
layer calls :func:`enforce` to turn a ``Deny`` into a problem+json response.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.errors import AppError, ErrorCode
from app.core.security.principal import Permission, Principal


@dataclass(frozen=True, slots=True)
class Allow:
    allowed: Literal[True] = True


@dataclass(frozen=True, slots=True)
class Deny:
    code: ErrorCode
    detail: str | None = None
    allowed: Literal[False] = False


type Decision = Allow | Deny

ALLOW = Allow()


def enforce(decision: Decision) -> None:
    if isinstance(decision, Deny):
        raise AppError(decision.code, decision.detail)


def authorize_platform(principal: Principal, permission: Permission) -> Decision:
    """Platform RBAC check for administrative actions."""
    if not principal.is_active:
        return Deny(ErrorCode.ACCOUNT_SUSPENDED, "Account is not active.")
    if not principal.has_permission(permission):
        return Deny(ErrorCode.FORBIDDEN, "Insufficient platform permissions.")
    return ALLOW
