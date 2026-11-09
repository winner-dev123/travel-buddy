from __future__ import annotations

import itertools

import pytest

from app.core.errors import AppError, ErrorCode
from app.core.ids import uuid7
from app.core.security.policy import ALLOW, Deny, authorize_platform, enforce
from app.core.security.principal import (
    MFA_METHOD,
    ROLE_PERMISSIONS,
    AccountStatus,
    Permission,
    PlatformRole,
    Principal,
)


def _principal(
    *roles: PlatformRole,
    status: AccountStatus = AccountStatus.ACTIVE,
    amr: frozenset[str] = frozenset({"password", MFA_METHOD}),
) -> Principal:
    return Principal(
        user_id=uuid7(),
        session_id=uuid7(),
        account_status=status,
        roles=frozenset(roles),
        amr=amr,
    )


def test_role_hierarchy_is_cumulative() -> None:
    order = [
        PlatformRole.SUPPORT,
        PlatformRole.MODERATOR,
        PlatformRole.ADMIN,
        PlatformRole.SUPERADMIN,
    ]
    for lower, higher in itertools.pairwise(order):
        assert ROLE_PERMISSIONS[lower] < ROLE_PERMISSIONS[higher]


def test_regular_user_has_no_platform_permissions() -> None:
    assert _principal().permissions == frozenset()


def test_suspended_admin_loses_permissions() -> None:
    admin = _principal(PlatformRole.ADMIN, status=AccountStatus.SUSPENDED)
    assert admin.permissions == frozenset()
    decision = authorize_platform(admin, Permission.MODERATION_ACTIONS_WRITE)
    assert isinstance(decision, Deny)
    assert decision.code is ErrorCode.ACCOUNT_SUSPENDED


@pytest.mark.req("ADM-001")
def test_moderator_can_act_but_cannot_grant_entitlements() -> None:
    moderator = _principal(PlatformRole.MODERATOR)
    assert authorize_platform(moderator, Permission.MODERATION_ACTIONS_WRITE) == ALLOW
    denied = authorize_platform(moderator, Permission.ENTITLEMENTS_GRANT)
    assert isinstance(denied, Deny)
    assert denied.code is ErrorCode.FORBIDDEN


def test_only_superadmin_assigns_roles() -> None:
    assert not _principal(PlatformRole.ADMIN).has_permission(Permission.ROLES_ASSIGN)
    assert _principal(PlatformRole.SUPERADMIN).has_permission(Permission.ROLES_ASSIGN)


def test_enforce_raises_for_deny_only() -> None:
    enforce(ALLOW)
    with pytest.raises(AppError) as excinfo:
        enforce(Deny(ErrorCode.CONNECTION_REQUIRED, "Connect first."))
    assert excinfo.value.code is ErrorCode.CONNECTION_REQUIRED
    assert excinfo.value.status == 403


@pytest.mark.req("ADM-007")
@pytest.mark.security
@pytest.mark.parametrize("role", list(PlatformRole))
def test_staff_without_mfa_are_denied_with_mfa_required(role: PlatformRole) -> None:
    staff = _principal(role, amr=frozenset({"password"}))
    permission = next(iter(ROLE_PERMISSIONS[role]))
    decision = authorize_platform(staff, permission)
    assert isinstance(decision, Deny)
    assert decision.code is ErrorCode.MFA_REQUIRED
    assert _principal(role).mfa_satisfied
    assert authorize_platform(_principal(role), permission) == ALLOW


@pytest.mark.req("ADM-007")
def test_non_staff_get_forbidden_not_an_mfa_hint() -> None:
    decision = authorize_platform(_principal(amr=frozenset()), Permission.USERS_READ)
    assert isinstance(decision, Deny)
    assert decision.code is ErrorCode.FORBIDDEN
