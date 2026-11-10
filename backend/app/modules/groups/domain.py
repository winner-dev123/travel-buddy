"""Group roles, permissions and limits (pure; GRP-007, GRP-009, docs/07 §5)."""

from __future__ import annotations

from datetime import timedelta
from enum import StrEnum
from typing import Final


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MODERATOR = "moderator"
    MEMBER = "member"


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    RESTRICTED = "restricted"
    REMOVED = "removed"
    LEFT = "left"


class GroupStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    SUSPENDED = "suspended"


class InvitationKind(StrEnum):
    DIRECT = "direct"
    LINK = "link"


class InvitationStatus(StrEnum):
    ACTIVE = "active"
    EXHAUSTED = "exhausted"
    REVOKED = "revoked"
    EXPIRED = "expired"
    ACCEPTED = "accepted"
    DECLINED = "declined"


class TransferStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class Permission(StrEnum):
    GROUP_EDIT = "group.edit"
    GROUP_DELETE = "group.delete"
    GROUP_TRANSFER = "group.transfer"
    MEMBERS_INVITE = "members.invite"
    MEMBERS_APPROVE = "members.approve"
    MEMBERS_REMOVE = "members.remove"
    MEMBERS_RESTRICT = "members.restrict"
    ROLES_ASSIGN = "roles.assign"
    MESSAGES_REMOVE = "messages.remove"
    MESSAGES_PIN = "messages.pin"
    ANNOUNCEMENTS_POST = "announcements.post"
    CHALLENGES_MANAGE = "challenges.manage"
    CHALLENGES_JUDGE = "challenges.judge"


P = Permission
RANK: Final = {Role.OWNER: 100, Role.ADMIN: 80, Role.MODERATOR: 50, Role.MEMBER: 10}

_ADMIN = frozenset(
    {
        P.GROUP_EDIT,
        P.MEMBERS_INVITE,
        P.MEMBERS_APPROVE,
        P.MEMBERS_REMOVE,
        P.MEMBERS_RESTRICT,
        P.ROLES_ASSIGN,
        P.MESSAGES_REMOVE,
        P.MESSAGES_PIN,
        P.ANNOUNCEMENTS_POST,
        P.CHALLENGES_MANAGE,
        P.CHALLENGES_JUDGE,
    }
)
ROLE_PERMISSIONS: Final[dict[Role, frozenset[Permission]]] = {
    Role.OWNER: frozenset(Permission),
    Role.ADMIN: _ADMIN,
    Role.MODERATOR: frozenset(
        {
            P.MEMBERS_REMOVE,
            P.MEMBERS_RESTRICT,
            P.MESSAGES_REMOVE,
            P.MESSAGES_PIN,
            P.CHALLENGES_JUDGE,
        }
    ),
    Role.MEMBER: frozenset(),
}

# Need the group's premium status (owner premium or admin grace); everything else — safety tools
# above all — keeps working after a lapse (docs/07 §5, GRP-009).
PREMIUM_GATED: Final = frozenset({P.MEMBERS_INVITE, P.MEMBERS_APPROVE, P.CHALLENGES_MANAGE})

MAX_CAPACITY: Final = 50
LINK_DEFAULT_TTL: Final = timedelta(hours=168)
LINK_MAX_TTL: Final = timedelta(hours=720)
DIRECT_INVITE_TTL: Final = timedelta(days=14)
TRANSFER_TTL: Final = timedelta(days=7)
MAX_RESTRICTION: Final = timedelta(days=30)


def permissions(
    role: Role, *, members_can_invite: bool, premium_active: bool
) -> frozenset[Permission]:
    """Effective permissions now: the role's set (plus inviting for members when the group allows
    it), minus premium-gated tools once the group's premium lapsed."""
    granted = set(ROLE_PERMISSIONS[role])
    if members_can_invite:
        granted.add(P.MEMBERS_INVITE)
    if not premium_active:
        granted -= PREMIUM_GATED
    return frozenset(granted)


def outranks(actor: Role, target: Role) -> bool:
    """Moderation and role changes only apply to members of a lower rank."""
    return RANK[actor] > RANK[target]


def assignable(actor: Role, new_role: Role) -> bool:
    """Roles below the actor's own rank; ownership moves only through a transfer."""
    return new_role is not Role.OWNER and RANK[new_role] < RANK[actor]
