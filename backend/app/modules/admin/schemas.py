"""Admin request/response models (mirror the contract's Admin* schemas)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.profiles.schemas import UserSummary

TargetType = Literal["post", "comment", "user", "message", "group", "challenge", "media"]
RestrictionKind = Literal[
    "posting_limited",
    "commenting_limited",
    "messaging_limited",
    "connection_requests_limited",
    "discovery_disabled",
    "media_upload_limited",
]
ActionType = Literal[
    "remove_content",
    "restore_content",
    "limit_visibility",
    "warn",
    "restrict",
    "suspend",
    "ban",
    "reinstate",
    "remove_member",
]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Response(BaseModel):
    model_config = ConfigDict(frozen=True)


class AdminReport(_Response):
    id: uuid.UUID
    reporter: UserSummary | None
    target_type: TargetType
    target_id: uuid.UUID
    target_author: UserSummary | None
    reason: str
    details: str | None
    priority: int
    status: Literal["open", "in_review", "actioned", "dismissed"]
    assigned_to: UserSummary | None
    evidence: dict[str, Any]
    resolution_note: str | None
    related_report_count: int
    created_at: datetime
    resolved_at: datetime | None


class AssignReportRequest(_Request):
    assignee_id: uuid.UUID


class ModerationActionRequest(_Request):
    target_type: TargetType
    target_id: uuid.UUID
    action: ActionType
    reason_code: str = Field(max_length=40)
    restriction_kind: RestrictionKind | None = None  # required for (and only for) ``restrict``
    notes: str | None = Field(default=None, max_length=2000)
    report_id: uuid.UUID | None = None
    expires_at: datetime | None = None


class ResolveReportRequest(_Request):
    status: Literal["actioned", "dismissed"]
    resolution_note: str = Field(min_length=3, max_length=2000)
    action: ModerationActionRequest | None = None


class ModerationActionOut(_Response):
    id: uuid.UUID
    scope: Literal["platform", "group"]
    group_id: uuid.UUID | None
    target_type: TargetType
    target_id: uuid.UUID
    action: ActionType
    restriction_kind: RestrictionKind | None
    reason_code: str
    notes: str | None
    actor: UserSummary | None
    report_id: uuid.UUID | None
    expires_at: datetime | None
    created_at: datetime


AccountStatus = Literal["active", "suspended", "deactivated", "pending_deletion", "deleted"]
StaffRole = Literal["support", "moderator", "admin", "superadmin"]


class AdminUserSummary(_Response):
    """Contract ``AdminUserSummary``: a search or list row. No email: open the user for it."""

    id: uuid.UUID
    handle: str
    display_name: str
    status: AccountStatus
    roles: list[StaffRole]
    created_at: datetime
    last_active_on: date | None


class AdminUser(_Response):
    id: uuid.UUID
    handle: str
    display_name: str
    status: AccountStatus
    email: str | None
    roles: list[StaffRole]
    created_at: datetime
    last_active_on: date | None
    open_report_count: int
    moderation_action_count: int
    suspended_until: datetime | None


class SuspendUserRequest(_Request):
    reason_code: str = Field(max_length=40)
    notes: str = Field(min_length=3, max_length=2000)
    until: datetime | None


class ReinstateUserRequest(_Request):
    notes: str = Field(min_length=3, max_length=1000)


class AdminDestinationUpdate(BaseModel):
    """At least one of the fields (DEST-004). ``cover_media_id: null`` removes the cover."""

    model_config = ConfigDict(extra="forbid")

    is_featured: bool | None = None
    status: Literal["active", "hidden"] | None = None
    cover_media_id: uuid.UUID | None = None

    @property
    def sets_cover(self) -> bool:
        return "cover_media_id" in self.model_fields_set

    @model_validator(mode="after")
    def _not_empty(self) -> AdminDestinationUpdate:
        if self.is_featured is None and self.status is None and not self.sets_cover:
            raise ValueError("Change is_featured, status or cover_media_id.")
        return self


class AuditLogEntry(_Response):
    """Contract ``AuditLogEntry``."""

    id: uuid.UUID
    occurred_at: datetime
    actor_id: uuid.UUID | None
    actor_type: Literal["user", "admin", "system", "service"]
    action: str
    resource_type: str
    resource_id: uuid.UUID | None
    scope_group_id: uuid.UUID | None
    request_id: str | None
    metadata: dict[str, Any]


class OpsSummary(_Response):
    """Contract ``OpsSummary`` (ADM-006)."""

    generated_at: datetime
    moderation: dict[str, Any]
    outbox: dict[str, Any]
    jobs: dict[str, Any]


class OverviewUsers(_Response):
    total: int
    new_7d: int
    new_30d: int
    active_7d: int
    suspended: int


class OverviewModeration(_Response):
    open_reports: int
    unassigned_reports: int
    oldest_open_age_seconds: int | None
    by_priority: dict[str, int]


class OverviewRevenue(_Response):
    currency: str
    environment: Literal["production", "sandbox"]
    amount_minor: int


class AdminOverview(_Response):
    """Contract ``AdminOverview``: real aggregates for the console home page. ``revenue_30d`` is
    null unless the caller may see billing (``entitlements.grant``)."""

    generated_at: datetime
    users: OverviewUsers
    premium_members: int
    posts_7d: int
    moderation: OverviewModeration
    open_data_requests: int | None
    revenue_30d: list[OverviewRevenue] | None
