"""The authenticated caller and platform-level RBAC (architecture section 9).

Platform roles grant *administrative* permissions only. Group roles are resource-scoped and are
evaluated by the groups module; they never appear here or in tokens.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class PlatformRole(StrEnum):
    SUPPORT = "support"
    MODERATOR = "moderator"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"


class Permission(StrEnum):
    """Mirrors ``PlatformPermission`` in contracts/openapi/openapi.yaml (contract test enforces)."""

    USERS_READ = "users.read"
    USERS_READ_SENSITIVE = "users.read_sensitive"  # requires justification + audit (ADM-003/009)
    USERS_SUSPEND = "users.suspend"
    USERS_BAN = "users.ban"
    MODERATION_REPORTS_READ = "moderation.reports.read"
    MODERATION_REPORTS_MANAGE = "moderation.reports.manage"
    MODERATION_ACTIONS_READ = "moderation.actions.read"
    MODERATION_ACTIONS_WRITE = "moderation.actions.write"
    CONTENT_DESTINATIONS_WRITE = "content.destinations.write"
    CONTENT_FEATURE = "content.feature"
    CONTENT_REWARDS_REVIEW = "content.rewards.review"
    ENTITLEMENTS_GRANT = "entitlements.grant"
    BILLING_CONFIGURE = "billing.configure"
    AUDIT_READ = "audit.read"
    ROLES_ASSIGN = "roles.assign"


_SUPPORT = frozenset(
    {
        Permission.USERS_READ,
        Permission.MODERATION_REPORTS_READ,
        Permission.MODERATION_ACTIONS_READ,
    }
)
_MODERATOR = _SUPPORT | {
    Permission.MODERATION_REPORTS_MANAGE,
    Permission.MODERATION_ACTIONS_WRITE,
    Permission.USERS_SUSPEND,
    Permission.CONTENT_REWARDS_REVIEW,
}
_ADMIN = _MODERATOR | {
    Permission.USERS_READ_SENSITIVE,
    Permission.USERS_BAN,
    Permission.CONTENT_DESTINATIONS_WRITE,
    Permission.CONTENT_FEATURE,
    Permission.ENTITLEMENTS_GRANT,
    Permission.AUDIT_READ,
}
_SUPERADMIN = _ADMIN | {Permission.BILLING_CONFIGURE, Permission.ROLES_ASSIGN}

ROLE_PERMISSIONS: Mapping[PlatformRole, frozenset[Permission]] = {
    PlatformRole.SUPPORT: frozenset(_SUPPORT),
    PlatformRole.MODERATOR: frozenset(_MODERATOR),
    PlatformRole.ADMIN: frozenset(_ADMIN),
    PlatformRole.SUPERADMIN: frozenset(_SUPERADMIN),
}


class AccountStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"
    PENDING_DELETION = "pending_deletion"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: uuid.UUID
    session_id: uuid.UUID
    account_status: AccountStatus = AccountStatus.ACTIVE
    roles: frozenset[PlatformRole] = field(default_factory=frozenset)
    email_verified: bool = False
    age_assured: bool = False

    @property
    def is_active(self) -> bool:
        return self.account_status is AccountStatus.ACTIVE

    @property
    def permissions(self) -> frozenset[Permission]:
        if not self.is_active:
            return frozenset()
        granted: set[Permission] = set()
        for role in self.roles:
            granted |= ROLE_PERMISSIONS[role]
        return frozenset(granted)

    def has_permission(self, permission: Permission) -> bool:
        return permission in self.permissions
