"""Staff guard for every ``/v1/admin/*`` route (ADM-007/008/009, threat T-AUTH-09).

Order of checks: authenticated → platform permission → second factor (``authorize_platform``) →
staff session limits (30 min idle / 12 h absolute, ADM-008) → audit justification header when the
route requires one (ADM-009). Non-staff callers therefore learn nothing about the later checks.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from app.core.errors import AppError, ErrorCode
from app.core.security.authn import get_principal
from app.core.security.policy import authorize_platform, enforce
from app.core.security.principal import Permission, Principal
from app.modules.identity import service as identity

JUSTIFICATION_MIN = 10
JUSTIFICATION_MAX = 500


@dataclass(frozen=True, slots=True)
class Staff:
    principal: Principal
    justification: str | None


def _justification(request: Request) -> str:
    value = (request.headers.get("x-audit-justification") or "").strip()
    if not JUSTIFICATION_MIN <= len(value) <= JUSTIFICATION_MAX:
        raise AppError(
            ErrorCode.JUSTIFICATION_REQUIRED,
            f"Explain why in the X-Audit-Justification header ({JUSTIFICATION_MIN}-"
            f"{JUSTIFICATION_MAX} characters).",
        )
    return value


def staff(permission: Permission, *, justified: bool = False) -> Callable[..., Awaitable[Staff]]:
    async def dependency(
        request: Request, principal: Annotated[Principal, Depends(get_principal)]
    ) -> Staff:
        enforce(authorize_platform(principal, permission))
        sessionmaker = request.app.state.database.sessionmaker
        async with sessionmaker() as session, session.begin():
            await identity.check_admin_session(
                session, principal, now=request.app.state.clock.now()
            )
        return Staff(
            principal=principal, justification=_justification(request) if justified else None
        )

    return dependency
