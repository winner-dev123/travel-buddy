"""Group API shapes (contract ``Group``, ``GroupSettings``, ``GroupMember``, invitations)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.pagination import PageInfo
from app.modules.destinations.schemas import DestinationSummary
from app.modules.media.schemas import MediaRef
from app.modules.profiles.schemas import UserSummary

RoleKey = Literal["owner", "admin", "moderator", "member"]
MembershipStatusName = Literal["active", "restricted", "removed", "left"]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Response(BaseModel):
    model_config = ConfigDict(frozen=True)


class CreateGroupRequest(_Request):
    name: str = Field(min_length=3, max_length=60)
    description: str | None = Field(default=None, max_length=1000)
    cover_media_id: uuid.UUID | None = None
    primary_destination_id: uuid.UUID
    trip_id: uuid.UUID | None = None
    start_date: date | None = None
    end_date: date | None = None
    visibility: Literal["private", "unlisted", "public"] = "private"
    join_policy: Literal["invite_only", "request_to_join"] = "invite_only"
    member_capacity: int = Field(default=20, ge=2, le=50)
    interests: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _dates(self) -> Self:
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class UpdateGroupRequest(_Request):
    nullable: ClassVar[frozenset[str]] = frozenset(
        {"description", "cover_media_id", "trip_id", "start_date", "end_date"}
    )

    name: str | None = Field(default=None, min_length=3, max_length=60)
    description: str | None = Field(default=None, max_length=1000)
    cover_media_id: uuid.UUID | None = None
    primary_destination_id: uuid.UUID | None = None
    trip_id: uuid.UUID | None = None
    start_date: date | None = None
    end_date: date | None = None
    visibility: Literal["private", "unlisted", "public"] | None = None
    join_policy: Literal["invite_only", "request_to_join"] | None = None
    member_capacity: int | None = Field(default=None, ge=2, le=50)
    interests: list[str] | None = Field(default=None, max_length=10)

    @model_validator(mode="after")
    def _present(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        for name in self.model_fields_set:
            if getattr(self, name) is None and name not in self.nullable:
                raise ValueError(f"{name} can't be null")
        return self


class UpdateGroupSettingsRequest(_Request):
    members_can_invite: bool | None = None
    chat_mode: Literal["everyone", "admins_only"] | None = None
    new_member_history: Literal["full", "from_join"] | None = None
    challenge_defaults: dict[str, Any] | None = None


class ChangeRoleRequest(_Request):
    role: Literal["admin", "moderator", "member"]


class RestrictMemberRequest(_Request):
    until: datetime
    reason_code: str | None = Field(default=None, max_length=40)


class DirectInvitationRequest(_Request):
    kind: Literal["direct"]
    invitee_user_id: uuid.UUID


class LinkInvitationRequest(_Request):
    kind: Literal["link"]
    max_uses: int = Field(default=10, ge=1, le=100)
    expires_in_hours: int = Field(default=168, ge=1, le=720)


class InvitationTokenRequest(_Request):
    token: str = Field(min_length=32, max_length=128)


class CreateTransferRequest(_Request):
    to_user_id: uuid.UUID


class AnnouncementRequest(_Request):
    client_message_id: uuid.UUID
    body: str = Field(min_length=1, max_length=4000)
    pin: bool = False


class MyGroupMembership(_Response):
    role: RoleKey
    status: MembershipStatusName
    permissions: list[str]
    restricted_until: datetime | None
    joined_at: datetime


class GroupOut(_Response):
    id: uuid.UUID
    name: str
    description: str | None
    cover: MediaRef | None
    primary_destination: DestinationSummary
    trip_id: uuid.UUID | None
    start_date: date | None
    end_date: date | None
    visibility: Literal["private", "unlisted", "public"]
    join_policy: Literal["invite_only", "request_to_join"]
    member_capacity: int
    member_count: int
    interests: list[str]
    owner: UserSummary
    status: Literal["active", "archived", "suspended"]
    conversation_id: uuid.UUID
    premium_features_active: bool
    premium_grace_until: datetime | None
    my_membership: MyGroupMembership | None
    version: int
    created_at: datetime
    updated_at: datetime


class GroupSummary(_Response):
    id: uuid.UUID
    name: str
    cover: MediaRef | None
    primary_destination: DestinationSummary
    start_date: date | None
    end_date: date | None
    member_count: int


class GroupPage(_Response):
    data: list[GroupOut]
    page: PageInfo


class GroupSettingsOut(_Response):
    members_can_invite: bool
    chat_mode: Literal["everyone", "admins_only"]
    new_member_history: Literal["full", "from_join"]
    challenge_defaults: dict[str, Any]
    version: int


class GroupRoleOut(_Response):
    key: RoleKey
    rank: int
    permissions: list[str]
    is_system: bool


class GroupRoleList(_Response):
    data: list[GroupRoleOut]


class GroupMemberOut(_Response):
    group_id: uuid.UUID
    user: UserSummary
    role: RoleKey
    status: MembershipStatusName
    joined_at: datetime
    restricted_until: datetime | None
    invited_by: UserSummary | None


class GroupMemberPage(_Response):
    data: list[GroupMemberOut]
    page: PageInfo


class GroupInvitationOut(_Response):
    id: uuid.UUID
    group: GroupSummary
    kind: Literal["direct", "link"]
    invitee: UserSummary | None
    created_by: UserSummary | None
    max_uses: int
    use_count: int
    expires_at: datetime
    status: Literal["active", "exhausted", "revoked", "expired", "accepted", "declined"]
    created_at: datetime


class GroupInvitationPage(_Response):
    data: list[GroupInvitationOut]
    page: PageInfo


class CreatedGroupInvitation(_Response):
    invitation: GroupInvitationOut
    token: str | None
    url: str | None


class GroupInvitationPreview(_Response):
    group: GroupSummary
    inviter: UserSummary | None
    expires_at: datetime
    is_member: bool


class OwnershipTransferOut(_Response):
    id: uuid.UUID
    group_id: uuid.UUID
    from_user: UserSummary
    to_user: UserSummary
    status: Literal["pending", "accepted", "declined", "cancelled", "expired"]
    created_at: datetime
    expires_at: datetime
    responded_at: datetime | None
