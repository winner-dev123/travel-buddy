"""Group authorization matrix (pure; GRP-007, GRP-009)."""

from __future__ import annotations

import pytest

from app.modules.groups.domain import (
    PREMIUM_GATED,
    Permission,
    Role,
    assignable,
    outranks,
    permissions,
)

P = Permission
SAFETY = {P.MEMBERS_REMOVE, P.MEMBERS_RESTRICT, P.MESSAGES_REMOVE}


@pytest.mark.req("GRP-007")
@pytest.mark.parametrize(
    ("role", "allowed", "denied"),
    [
        (Role.OWNER, set(Permission), set()),
        (
            Role.ADMIN,
            {P.GROUP_EDIT, P.ROLES_ASSIGN, P.ANNOUNCEMENTS_POST, *SAFETY},
            {P.GROUP_TRANSFER, P.GROUP_DELETE},
        ),
        (
            Role.MODERATOR,
            {*SAFETY, P.MESSAGES_PIN},
            {P.GROUP_EDIT, P.ROLES_ASSIGN, P.MEMBERS_INVITE},
        ),
        (Role.MEMBER, set(), set(Permission)),
    ],
)
def test_role_matrix(role: Role, allowed: set[Permission], denied: set[Permission]) -> None:
    granted = permissions(role, members_can_invite=False, premium_active=True)
    assert allowed <= granted
    assert not (denied & granted)


def test_members_invite_only_when_the_group_allows_it() -> None:
    assert P.MEMBERS_INVITE in permissions(
        Role.MEMBER, members_can_invite=True, premium_active=True
    )
    assert P.MEMBERS_INVITE not in permissions(
        Role.MEMBER, members_can_invite=False, premium_active=True
    )


@pytest.mark.req("GRP-009")
@pytest.mark.parametrize("role", list(Role))
def test_lapse_removes_only_premium_tools(role: Role) -> None:
    active = permissions(role, members_can_invite=True, premium_active=True)
    lapsed = permissions(role, members_can_invite=True, premium_active=False)
    assert active - lapsed <= PREMIUM_GATED
    assert (active & SAFETY) == (lapsed & SAFETY)  # safety tools never lapse


def test_rank_rules() -> None:
    assert outranks(Role.MODERATOR, Role.MEMBER)
    assert not outranks(Role.MODERATOR, Role.MODERATOR)
    assert not outranks(Role.ADMIN, Role.OWNER)
    assert assignable(Role.ADMIN, Role.MODERATOR)
    assert not assignable(Role.ADMIN, Role.ADMIN)
    assert not assignable(Role.OWNER, Role.OWNER)  # ownership moves only by transfer


@pytest.mark.req("GRP-009")
def test_lapse_notices_fire_once_per_stage() -> None:
    from datetime import UTC, datetime, timedelta

    from app.modules.groups.service import lapse_notice

    now = datetime(2026, 11, 10, tzinfo=UTC)
    far, near = now + timedelta(days=10), now + timedelta(days=2)
    assert lapse_notice("active", None, now, None) is None
    assert lapse_notice("grace", far, now, None) == "grace"
    assert lapse_notice("grace", far, now, "grace") is None
    assert lapse_notice("grace", near, now, "grace") == "grace_ending"
    assert lapse_notice("grace", near, now, "grace_ending") is None
    assert lapse_notice("lapsed", None, now, "grace_ending") == "lapsed"
    assert lapse_notice("lapsed", None, now, None) == "lapsed"  # refunds skip the grace
    assert lapse_notice("lapsed", None, now, "lapsed") is None
