"""Travel companion groups (BL-3.07..3.10; GRP-001..013, docs/07 §5).

- Creating a group needs the ``groups.create`` entitlement and room under the owned-group quota,
  both checked server-side through billing. The creator becomes the owner; the group chat is
  created in the same transaction (GCHAT-001). v1 groups are private and invite-only.
- Joining never needs a subscription (GRP-008). Capacity is enforced under a row lock on the
  group, so concurrent joins never exceed it (GRP-012). Link invitations store only the token's
  hash; redemption locks the invitation and checks status, expiry, uses and capacity together.
- Permissions come from a fixed role matrix; moderation and role changes only reach lower ranks.
  After the owner's premium (and the admin grace) lapse, only inviting, approving and challenges
  stop; safety tools always work and data is never deleted (GRP-009, GRP-011).
- Members who leave or are removed lose the chat immediately (GCHAT-007).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.pagination import CursorCodec, PageInfo
from app.core.security.principal import Principal
from app.core.time import Clock
from app.modules.billing import service as billing
from app.modules.destinations import service as destinations
from app.modules.groups.domain import (
    DIRECT_INVITE_TTL,
    MAX_RESTRICTION,
    RANK,
    ROLE_PERMISSIONS,
    TRANSFER_TTL,
    GroupStatus,
    InvitationKind,
    InvitationStatus,
    MembershipStatus,
    Permission,
    Role,
    TransferStatus,
    assignable,
    outranks,
    permissions,
)
from app.modules.groups.models import (
    GroupInvitation,
    GroupMembership,
    GroupOwnershipTransfer,
    GroupSettings,
    TravelGroup,
)
from app.modules.groups.schemas import (
    CreatedGroupInvitation,
    CreateGroupRequest,
    DirectInvitationRequest,
    GroupInvitationOut,
    GroupInvitationPage,
    GroupInvitationPreview,
    GroupMemberOut,
    GroupMemberPage,
    GroupOut,
    GroupPage,
    GroupRoleList,
    GroupRoleOut,
    GroupSettingsOut,
    GroupSummary,
    LinkInvitationRequest,
    MyGroupMembership,
    OwnershipTransferOut,
    UpdateGroupRequest,
    UpdateGroupSettingsRequest,
)
from app.modules.identity import service as identity
from app.modules.media import service as media
from app.modules.platform import service as platform
from app.modules.profiles import service as profiles
from app.modules.trust_safety import service as trust_safety

CREATE_ROUTE = "POST /v1/groups"
_MEMBER = (MembershipStatus.ACTIVE, MembershipStatus.RESTRICTED)


class GroupChat(Protocol):
    """The group's chat room, provided by messaging (same layer; wired in main)."""

    async def create(
        self, session: AsyncSession, group_id: uuid.UUID, owner_id: uuid.UUID
    ) -> uuid.UUID: ...

    async def add_member(
        self,
        session: AsyncSession,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        from_join: bool,
    ) -> None: ...

    async def remove_member(
        self, session: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID
    ) -> None: ...


# Posts an announcement as ``sender`` (permission already checked); returns the Message JSON.
Announce = Callable[[Principal, uuid.UUID, uuid.UUID, str, bool], Awaitable[dict[str, Any]]]


@dataclass(frozen=True, slots=True)
class ChatPolicy:
    """What the group decides about one member's chat rights (read by messaging)."""

    restriction: str | None
    permissions: frozenset[str]
    title: str | None = None


def _not_found() -> AppError:
    return AppError(ErrorCode.NOT_FOUND, "Group not found.")


def _forbidden(message: str = "You can't do that in this group.") -> AppError:
    return AppError(ErrorCode.FORBIDDEN, message)


def _invalid(field: str, message: str) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_FAILED,
        message,
        errors=[FieldError(field=field, code="invalid", message=message)],
    )


def _entitlement_required(feature: str = "members.invite") -> AppError:
    return AppError(
        ErrorCode.ENTITLEMENT_REQUIRED,
        "The group owner's premium has ended, so this isn't available right now.",
        extensions={"entitlement": feature},
    )


def _token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def _check_version(current: int, if_match: str | None) -> None:
    if if_match is None:
        raise AppError(
            ErrorCode.PRECONDITION_REQUIRED, "Send If-Match with the version you edited."
        )
    if if_match.strip().strip('"') != str(current):
        raise AppError(
            ErrorCode.PRECONDITION_FAILED, "Someone else changed this. Reload and try again."
        )


@dataclass(slots=True)
class _Context:
    group: TravelGroup
    settings: GroupSettings
    membership: GroupMembership | None
    premium_active: bool
    premium_grace_until: datetime | None

    @property
    def role(self) -> Role | None:
        return Role(self.membership.role) if self.membership else None

    def permissions(self) -> frozenset[Permission]:
        if self.membership is None or self.membership.status not in _MEMBER:
            return frozenset()
        return permissions(
            Role(self.membership.role),
            members_can_invite=self.settings.members_can_invite,
            premium_active=self.premium_active,
        )


class GroupService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        clock: Clock,
        cursors: CursorCodec,
        chat: GroupChat,
        announce: Announce | None = None,
        public_site_url: str = "http://localhost:3000",
    ) -> None:
        self._sessionmaker = sessionmaker
        self._clock = clock
        self._cursors = cursors
        self._chat = chat
        self._announce = announce
        self._site = public_site_url.rstrip("/")

    # ─────────────────────────────── loading ───────────────────────────────

    async def _context(
        self, session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID, *, lock: bool = False
    ) -> _Context:
        group = await session.get(TravelGroup, group_id, with_for_update=lock)
        if group is None:
            raise _not_found()
        membership = await session.scalar(
            select(GroupMembership).where(
                GroupMembership.group_id == group_id, GroupMembership.user_id == user_id
            )
        )
        if membership is not None and membership.status not in _MEMBER:
            membership = None
        if membership is None:
            raise _not_found()  # private groups are invisible to non-members
        settings = await session.get(GroupSettings, group_id)
        assert settings is not None
        await self._expire_restriction(membership)
        status = await billing.group_premium(session, group.owner_id, at=self._clock.now())
        return _Context(
            group, settings, membership, status.premium_features_active, status.grace_until
        )

    async def _expire_restriction(self, membership: GroupMembership) -> None:
        if (
            membership.status == MembershipStatus.RESTRICTED
            and membership.restricted_until is not None
            and membership.restricted_until <= self._clock.now()
        ):
            membership.status = MembershipStatus.ACTIVE
            membership.restricted_until = None

    async def _member_count(self, session: AsyncSession, group_id: uuid.UUID) -> int:
        return int(
            await session.scalar(
                select(func.count())
                .select_from(GroupMembership)
                .where(GroupMembership.group_id == group_id, GroupMembership.status.in_(_MEMBER))
            )
            or 0
        )

    async def _summaries(
        self, session: AsyncSession, groups: Sequence[TravelGroup], locale: str = "en"
    ) -> dict[uuid.UUID, GroupSummary]:
        if not groups:
            return {}
        places = await destinations.summaries_by_id(
            session, list({g.primary_destination_id for g in groups}), [locale]
        )
        covers = await media.refs(session, [g.cover_media_id for g in groups if g.cover_media_id])
        counted = await session.execute(
            select(GroupMembership.group_id, func.count())
            .where(
                GroupMembership.group_id.in_([g.id for g in groups]),
                GroupMembership.status.in_(_MEMBER),
            )
            .group_by(GroupMembership.group_id)
        )
        counts: dict[uuid.UUID, int] = {row[0]: int(row[1]) for row in counted.all()}
        return {
            g.id: GroupSummary(
                id=g.id,
                name=g.name,
                cover=covers.get(g.cover_media_id) if g.cover_media_id else None,
                primary_destination=places[g.primary_destination_id],
                start_date=g.start_date,
                end_date=g.end_date,
                member_count=int(counts.get(g.id, 0)),
            )
            for g in groups
            if g.primary_destination_id in places
        }

    async def _out(self, session: AsyncSession, context: _Context, locale: str = "en") -> GroupOut:
        group = context.group
        summary = (await self._summaries(session, [group], locale))[group.id]
        owners = await profiles.authors(session, [group.owner_id] if group.owner_id else [])
        owner = owners.get(group.owner_id) if group.owner_id else None
        membership = context.membership
        return GroupOut(
            id=group.id,
            name=group.name,
            description=group.description,
            cover=summary.cover,
            primary_destination=summary.primary_destination,
            trip_id=group.trip_id,
            start_date=group.start_date,
            end_date=group.end_date,
            visibility=group.visibility,  # type: ignore[arg-type]
            join_policy=group.join_policy,  # type: ignore[arg-type]
            member_capacity=group.member_capacity,
            member_count=summary.member_count,
            interests=list(group.interests),
            owner=profiles.user_summary(owner) if owner else None,
            status=group.status,  # type: ignore[arg-type]
            conversation_id=group.conversation_id,  # type: ignore[arg-type]
            premium_features_active=context.premium_active,
            premium_grace_until=context.premium_grace_until,
            my_membership=(
                MyGroupMembership(
                    role=membership.role,  # type: ignore[arg-type]
                    status=membership.status,  # type: ignore[arg-type]
                    permissions=sorted(p.value for p in context.permissions()),
                    restricted_until=membership.restricted_until,
                    joined_at=membership.joined_at,
                )
                if membership
                else None
            ),
            version=group.version,
            created_at=group.created_at,
            updated_at=group.updated_at,
        )

    async def _members_out(
        self, session: AsyncSession, rows: Sequence[GroupMembership]
    ) -> list[GroupMemberOut]:
        users = await profiles.authors(
            session,
            list({r.user_id for r in rows} | {r.invited_by for r in rows if r.invited_by}),
        )
        return [
            GroupMemberOut(
                group_id=r.group_id,
                user=profiles.user_summary(users[r.user_id]),
                role=r.role,  # type: ignore[arg-type]
                status=r.status,  # type: ignore[arg-type]
                joined_at=r.joined_at,
                restricted_until=r.restricted_until,
                invited_by=(
                    profiles.user_summary(users[r.invited_by])
                    if r.invited_by and r.invited_by in users
                    else None
                ),
            )
            for r in rows
            if r.user_id in users
        ]

    # ─────────────────────────────── groups ───────────────────────────────

    async def create(
        self, principal: Principal, request: CreateGroupRequest, *, idempotency_key: uuid.UUID
    ) -> GroupOut:
        me, now = principal.user_id, self._clock.now()
        if request.visibility != "private" or request.join_policy != "invite_only":
            raise AppError(
                ErrorCode.FEATURE_DISABLED, "Groups are private and invite-only for now."
            )
        async with self._sessionmaker() as session, session.begin():
            replay = await platform.idempotency.claim(
                session,
                user_id=me,
                key=idempotency_key,
                route=CREATE_ROUTE,
                payload=request.model_dump(mode="json"),
            )
            if replay is not None:
                return GroupOut.model_validate(replay.body)
            if not await billing.has(session, me, billing.Feature.GROUPS_CREATE, at=now):
                raise AppError(
                    ErrorCode.ENTITLEMENT_REQUIRED,
                    "Creating groups is a premium feature.",
                    extensions={"entitlement": billing.Feature.GROUPS_CREATE.value},
                )
            owned = await session.scalar(
                select(func.count())
                .select_from(TravelGroup)
                .where(TravelGroup.owner_id == me, TravelGroup.status == GroupStatus.ACTIVE)
            )
            limit = await billing.quota_limit(session, me, billing.Quota.GROUPS_OWNED, at=now)
            if (owned or 0) >= limit:
                raise AppError(
                    ErrorCode.QUOTA_EXCEEDED,
                    f"You can own up to {limit} active groups. Archive or transfer one first.",
                    status=409,
                )
            if not await destinations.is_active(session, request.primary_destination_id):
                raise _invalid("/primary_destination_id", "Pick a destination from the list.")
            if request.cover_media_id is not None and request.cover_media_id not in (
                await media.usable_ids(session, me, [request.cover_media_id], "group_cover")
            ):
                raise _invalid("/cover_media_id", "Upload the cover image first.")
            group = TravelGroup(
                name=request.name.strip(),
                description=(request.description or "").strip() or None,
                cover_media_id=request.cover_media_id,
                primary_destination_id=request.primary_destination_id,
                trip_id=request.trip_id,
                start_date=request.start_date,
                end_date=request.end_date,
                member_capacity=request.member_capacity,
                interests=[i.strip().lower() for i in request.interests if i.strip()],
                owner_id=me,
                created_by=me,
            )
            session.add(group)
            await session.flush()
            settings = GroupSettings(group_id=group.id)
            membership = GroupMembership(group_id=group.id, user_id=me, role=Role.OWNER)
            session.add_all([settings, membership])
            group.conversation_id = await self._chat.create(session, group.id, me)
            await session.flush()
            await session.refresh(group)
            await session.refresh(settings)
            await session.refresh(membership)
            platform.record_event(
                session,
                aggregate_type="group",
                aggregate_id=group.id,
                event_type="group.created",
                payload={"group_id": str(group.id), "owner_id": str(me)},
            )
            status = await billing.group_premium(session, me, at=now)
            out = await self._out(
                session,
                _Context(
                    group, settings, membership, status.premium_features_active, status.grace_until
                ),
            )
            await platform.idempotency.complete(
                session,
                user_id=me,
                key=idempotency_key,
                status=201,
                body=out.model_dump(mode="json"),
            )
        return out

    async def list_mine(
        self, user_id: uuid.UUID, *, role: str | None, cursor: str | None, limit: int
    ) -> GroupPage:
        scope = f"groups.{user_id}.{role or 'all'}"
        conditions = [GroupMembership.user_id == user_id, GroupMembership.status.in_(_MEMBER)]
        if role:
            conditions.append(GroupMembership.role == role)
        if cursor:
            position = self._cursors.decode(cursor, scope=scope)
            conditions.append(TravelGroup.id < uuid.UUID(str(position["id"])))
        async with self._sessionmaker() as session:
            ids = list(
                await session.scalars(
                    select(TravelGroup.id)
                    .join(GroupMembership, GroupMembership.group_id == TravelGroup.id)
                    .where(*conditions)
                    .order_by(TravelGroup.id.desc())
                    .limit(limit + 1)
                )
            )
            has_more = len(ids) > limit
            ids = ids[:limit]
            data = [
                await self._out(session, await self._context(session, gid, user_id)) for gid in ids
            ]
        next_cursor = (
            self._cursors.encode({"id": str(ids[-1])}, scope=scope) if has_more and ids else None
        )
        return GroupPage(data=data, page=PageInfo(next_cursor=next_cursor, has_more=has_more))

    async def get(self, user_id: uuid.UUID, group_id: uuid.UUID) -> GroupOut:
        async with self._sessionmaker() as session:
            context = await self._context(session, group_id, user_id)
            return await self._out(session, context)

    async def update(
        self,
        user_id: uuid.UUID,
        group_id: uuid.UUID,
        request: UpdateGroupRequest,
        *,
        if_match: str | None,
    ) -> GroupOut:
        async with self._sessionmaker() as session, session.begin():
            context = await self._context(session, group_id, user_id, lock=True)
            if Permission.GROUP_EDIT not in context.permissions():
                raise _forbidden()
            group = context.group
            _check_version(group.version, if_match)
            changes = request.model_dump(exclude_unset=True)
            if (
                changes.get("visibility", "private") != "private"
                or changes.get("join_policy", "invite_only") != "invite_only"
            ):
                raise AppError(
                    ErrorCode.FEATURE_DISABLED, "Groups are private and invite-only for now."
                )
            capacity = changes.get("member_capacity")
            if (
                capacity is not None
                and capacity > group.member_capacity
                and not context.premium_active
            ):
                raise _entitlement_required("groups.create")
            if capacity is not None and capacity < await self._member_count(session, group.id):
                raise _invalid("/member_capacity", "The group already has more members than that.")
            if "primary_destination_id" in changes and not await destinations.is_active(
                session, changes["primary_destination_id"]
            ):
                raise _invalid("/primary_destination_id", "Pick a destination from the list.")
            if changes.get("cover_media_id") and changes["cover_media_id"] not in (
                await media.usable_ids(session, user_id, [changes["cover_media_id"]], "group_cover")
            ):
                raise _invalid("/cover_media_id", "Upload the cover image first.")
            start = changes.get("start_date", group.start_date)
            end = changes.get("end_date", group.end_date)
            if start and end and start > end:
                raise _invalid("/end_date", "The end date must be on or after the start date.")
            for field, value in changes.items():
                if field == "interests":
                    value = [i.strip().lower() for i in value if i.strip()]
                setattr(group, field, value)
            group.version += 1
            await session.flush()
            await session.refresh(group)
            return await self._out(session, context)

    async def archive(self, user_id: uuid.UUID, group_id: uuid.UUID) -> GroupOut:
        """Owner only; data stays and chat turns read-only (GRP-011)."""
        async with self._sessionmaker() as session, session.begin():
            context = await self._context(session, group_id, user_id, lock=True)
            if context.role is not Role.OWNER:
                raise _forbidden("Only the owner can archive the group.")
            group = context.group
            if group.status != GroupStatus.ARCHIVED:
                group.status = GroupStatus.ARCHIVED
                group.archived_at = self._clock.now()
                group.version += 1
                await session.execute(
                    update(GroupInvitation)
                    .where(
                        GroupInvitation.group_id == group.id,
                        GroupInvitation.status == InvitationStatus.ACTIVE,
                    )
                    .values(
                        status=InvitationStatus.REVOKED, revoked_at=func.now(), revoked_by=user_id
                    )
                )
                await session.flush()
                await session.refresh(group)
            return await self._out(session, context)

    # ─────────────────────────────── settings and roles ───────────────────────────────

    @staticmethod
    def _settings_out(row: GroupSettings) -> GroupSettingsOut:
        return GroupSettingsOut(
            members_can_invite=row.members_can_invite,
            chat_mode=row.chat_mode,  # type: ignore[arg-type]
            new_member_history=row.new_member_history,  # type: ignore[arg-type]
            challenge_defaults=dict(row.challenge_defaults or {}),
            version=row.version,
        )

    async def get_settings(self, user_id: uuid.UUID, group_id: uuid.UUID) -> GroupSettingsOut:
        async with self._sessionmaker() as session:
            context = await self._context(session, group_id, user_id)
            return self._settings_out(context.settings)

    async def update_settings(
        self,
        user_id: uuid.UUID,
        group_id: uuid.UUID,
        request: UpdateGroupSettingsRequest,
        *,
        if_match: str | None,
    ) -> GroupSettingsOut:
        async with self._sessionmaker() as session, session.begin():
            context = await self._context(session, group_id, user_id, lock=True)
            if Permission.GROUP_EDIT not in context.permissions():
                raise _forbidden()
            settings = context.settings
            _check_version(settings.version, if_match)
            for field, value in request.model_dump(exclude_unset=True, exclude_none=True).items():
                setattr(settings, field, value)
            settings.version += 1
            await session.flush()
            await session.refresh(settings)
            return self._settings_out(settings)

    @staticmethod
    def roles() -> GroupRoleList:
        return GroupRoleList(
            data=[
                GroupRoleOut(
                    key=role.value,
                    rank=RANK[role],
                    permissions=sorted(p.value for p in ROLE_PERMISSIONS[role]),
                    is_system=True,
                )
                for role in sorted(Role, key=lambda r: -RANK[r])
            ]
        )

    async def check_member(self, user_id: uuid.UUID, group_id: uuid.UUID) -> None:
        async with self._sessionmaker() as session:
            await self._context(session, group_id, user_id)

    # ─────────────────────────────── members ───────────────────────────────

    async def members(
        self,
        user_id: uuid.UUID,
        group_id: uuid.UUID,
        *,
        status: str | None,
        cursor: str | None,
        limit: int,
    ) -> GroupMemberPage:
        scope = f"group-members.{group_id}.{status or 'current'}"
        async with self._sessionmaker() as session:
            context = await self._context(session, group_id, user_id)
            statuses = [status] if status else list(_MEMBER)
            if status in (MembershipStatus.REMOVED, MembershipStatus.LEFT) and (
                Permission.MEMBERS_REMOVE not in context.permissions()
            ):
                raise _forbidden()
            conditions = [
                GroupMembership.group_id == group_id,
                GroupMembership.status.in_(statuses),
            ]
            if cursor:
                position = self._cursors.decode(cursor, scope=scope)
                conditions.append(GroupMembership.id > uuid.UUID(str(position["id"])))
            rows = list(
                await session.scalars(
                    select(GroupMembership)
                    .where(*conditions)
                    .order_by(GroupMembership.id)
                    .limit(limit + 1)
                )
            )
            has_more = len(rows) > limit
            rows = rows[:limit]
            data = await self._members_out(session, rows)
        next_cursor = (
            self._cursors.encode({"id": str(rows[-1].id)}, scope=scope)
            if has_more and rows
            else None
        )
        return GroupMemberPage(data=data, page=PageInfo(next_cursor=next_cursor, has_more=has_more))

    async def _target(
        self, session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID
    ) -> GroupMembership:
        target = await session.scalar(
            select(GroupMembership)
            .where(GroupMembership.group_id == group_id, GroupMembership.user_id == user_id)
            .with_for_update()
        )
        if target is None or target.status not in _MEMBER:
            raise AppError(ErrorCode.NOT_FOUND, "Member not found.")
        return target

    async def change_role(
        self, actor_id: uuid.UUID, group_id: uuid.UUID, user_id: uuid.UUID, role: str
    ) -> GroupMemberOut:
        async with self._sessionmaker() as session, session.begin():
            context = await self._context(session, group_id, actor_id, lock=True)
            actor = context.role
            assert actor is not None
            if Permission.ROLES_ASSIGN not in context.permissions():
                raise _forbidden()
            target = await self._target(session, group_id, user_id)
            new_role = Role(role)
            if (
                actor_id == user_id
                or not outranks(actor, Role(target.role))
                or not assignable(actor, new_role)
            ):
                raise _forbidden("You can only assign roles below your own.")
            target.role = new_role
            await session.flush()
            [out] = await self._members_out(session, [target])
            return out

    async def remove_member(
        self, actor_id: uuid.UUID, group_id: uuid.UUID, user_id: uuid.UUID, *, reason: str | None
    ) -> None:
        """Safety tool: never paywalled (GRP-009); the chat goes with it at once (GCHAT-007)."""
        async with self._sessionmaker() as session, session.begin():
            context = await self._context(session, group_id, actor_id, lock=True)
            actor = context.role
            assert actor is not None
            if Permission.MEMBERS_REMOVE not in context.permissions():
                raise _forbidden()
            target = await self._target(session, group_id, user_id)
            if actor_id == user_id or not outranks(actor, Role(target.role)):
                raise _forbidden("You can only remove members below your role.")
            target.status = MembershipStatus.REMOVED
            target.removed_by = actor_id
            target.removed_at = self._clock.now()
            target.removal_reason = reason
            await self._chat.remove_member(session, context.group.conversation_id, user_id)  # type: ignore[arg-type]
            await trust_safety.record_action(
                session,
                target_type="user",
                target_id=user_id,
                action="remove_member",
                reason_code=reason or "group_moderation",
                notes=None,
                actor_id=actor_id,
                report_id=None,
                expires_at=None,
                group_id=group_id,
            )
            platform.record_event(
                session,
                aggregate_type="group",
                aggregate_id=group_id,
                event_type="group.member_removed",
                payload={"group_id": str(group_id), "user_id": str(user_id)},
            )

    async def restrict(
        self,
        actor_id: uuid.UUID,
        group_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        until: datetime | None,
        reason: str | None,
    ) -> GroupMemberOut | None:
        """Restricted members read but can't send (GCHAT-004); ``until=None`` lifts it."""
        now = self._clock.now()
        if until is not None and not (now < until <= now + MAX_RESTRICTION):
            raise _invalid("/until", "Restrict for up to 30 days from now.")
        async with self._sessionmaker() as session, session.begin():
            context = await self._context(session, group_id, actor_id, lock=True)
            actor = context.role
            assert actor is not None
            if Permission.MEMBERS_RESTRICT not in context.permissions():
                raise _forbidden()
            target = await self._target(session, group_id, user_id)
            if actor_id == user_id or not outranks(actor, Role(target.role)):
                raise _forbidden("You can only restrict members below your role.")
            target.status = MembershipStatus.RESTRICTED if until else MembershipStatus.ACTIVE
            target.restricted_until = until
            if until is not None:
                await trust_safety.record_action(
                    session,
                    target_type="user",
                    target_id=user_id,
                    action="restrict",
                    reason_code=reason or "group_moderation",
                    notes=None,
                    actor_id=actor_id,
                    report_id=None,
                    expires_at=until,
                    restriction_kind="messaging_limited",
                    group_id=group_id,
                )
            await session.flush()
            [out] = await self._members_out(session, [target])
            return out if until else None

    async def leave(self, user_id: uuid.UUID, group_id: uuid.UUID) -> None:
        async with self._sessionmaker() as session, session.begin():
            context = await self._context(session, group_id, user_id, lock=True)
            if context.role is Role.OWNER:
                raise AppError(ErrorCode.CONFLICT, "Transfer ownership before leaving your group.")
            membership = context.membership
            assert membership is not None
            membership.status = MembershipStatus.LEFT
            membership.removed_at = self._clock.now()
            await self._chat.remove_member(session, context.group.conversation_id, user_id)  # type: ignore[arg-type]

    async def _join(
        self,
        session: AsyncSession,
        group: TravelGroup,
        settings: GroupSettings,
        user_id: uuid.UUID,
        *,
        invited_by: uuid.UUID | None,
    ) -> tuple[GroupMembership, bool]:
        """Add a member under the group row lock (capacity, GRP-012). Returns (row, joined)."""
        existing = await session.scalar(
            select(GroupMembership)
            .where(GroupMembership.group_id == group.id, GroupMembership.user_id == user_id)
            .with_for_update()
        )
        if existing is not None and existing.status in _MEMBER:
            return existing, False
        if group.status != GroupStatus.ACTIVE:
            raise AppError(
                ErrorCode.INVITATION_INVALID, "This group isn't accepting members.", status=409
            )
        if await self._member_count(session, group.id) >= group.member_capacity:
            raise AppError(ErrorCode.GROUP_CAPACITY_REACHED, "This group is full.")
        if existing is not None:  # rejoining after leaving or removal (by a new invitation)
            existing.status = MembershipStatus.ACTIVE
            existing.role = Role.MEMBER
            existing.joined_at = self._clock.now()
            existing.invited_by = invited_by
            existing.removed_at = existing.removed_by = existing.removal_reason = None
            existing.restricted_until = None
            membership = existing
        else:
            membership = GroupMembership(
                group_id=group.id, user_id=user_id, role=Role.MEMBER, invited_by=invited_by
            )
            session.add(membership)
        await session.flush()
        await session.refresh(membership)
        await self._chat.add_member(
            session,
            group.conversation_id,  # type: ignore[arg-type]
            user_id,
            from_join=settings.new_member_history == "from_join",
        )
        platform.record_event(
            session,
            aggregate_type="group",
            aggregate_id=group.id,
            event_type="group.member_joined",
            payload={"group_id": str(group.id), "user_id": str(user_id)},
        )
        return membership, True

    # ─────────────────────────────── invitations ───────────────────────────────

    async def _invitations_out(
        self, session: AsyncSession, rows: Sequence[GroupInvitation]
    ) -> list[GroupInvitationOut]:
        groups = (
            list(
                await session.scalars(
                    select(TravelGroup).where(TravelGroup.id.in_({r.group_id for r in rows}))
                )
            )
            if rows
            else []
        )
        summaries = await self._summaries(session, groups)
        users = await profiles.authors(
            session,
            list({u for r in rows for u in (r.invitee_user_id, r.created_by) if u}),
        )
        now = self._clock.now()
        out = []
        for r in rows:
            if r.group_id not in summaries:
                continue
            status = r.status
            if status == InvitationStatus.ACTIVE and r.expires_at <= now:
                status = InvitationStatus.EXPIRED
            out.append(
                GroupInvitationOut(
                    id=r.id,
                    group=summaries[r.group_id],
                    kind=r.kind,  # type: ignore[arg-type]
                    invitee=profiles.user_summary(users[r.invitee_user_id])
                    if r.invitee_user_id in users
                    else None,
                    created_by=profiles.user_summary(users[r.created_by])
                    if r.created_by in users
                    else None,
                    max_uses=r.max_uses,
                    use_count=r.use_count,
                    expires_at=r.expires_at,
                    status=status,  # type: ignore[arg-type]
                    created_at=r.created_at,
                )
            )
        return out

    async def invite(
        self,
        user_id: uuid.UUID,
        group_id: uuid.UUID,
        request: DirectInvitationRequest | LinkInvitationRequest,
    ) -> CreatedGroupInvitation:
        now = self._clock.now()
        async with self._sessionmaker() as session, session.begin():
            context = await self._context(session, group_id, user_id, lock=True)
            if context.group.status != GroupStatus.ACTIVE:
                raise AppError(ErrorCode.CONFLICT, "This group is archived.")
            role = context.role
            assert role is not None
            allowed = permissions(
                role, members_can_invite=context.settings.members_can_invite, premium_active=True
            )
            if Permission.MEMBERS_INVITE not in allowed:
                raise _forbidden("Only admins can invite to this group.")
            if Permission.MEMBERS_INVITE not in context.permissions():
                raise _entitlement_required()
            token: str | None = None
            if isinstance(request, DirectInvitationRequest):
                invitee = request.invitee_user_id
                if invitee == user_id or not await identity.is_active(session, invitee):
                    raise AppError(ErrorCode.NOT_FOUND, "Traveller not found.")
                if await trust_safety.is_blocked(session, user_id, invitee):
                    raise AppError(ErrorCode.NOT_FOUND, "Traveller not found.")
                member = await session.scalar(
                    select(GroupMembership.status).where(
                        GroupMembership.group_id == group_id, GroupMembership.user_id == invitee
                    )
                )
                if member in _MEMBER:
                    raise AppError(ErrorCode.CONFLICT, "They're already in the group.")
                await session.execute(
                    update(GroupInvitation)
                    .where(
                        GroupInvitation.group_id == group_id,
                        GroupInvitation.invitee_user_id == invitee,
                        GroupInvitation.status == InvitationStatus.ACTIVE,
                    )
                    .values(
                        status=InvitationStatus.REVOKED, revoked_at=func.now(), revoked_by=user_id
                    )
                )
                row = GroupInvitation(
                    group_id=group_id,
                    kind=InvitationKind.DIRECT,
                    invitee_user_id=invitee,
                    created_by=user_id,
                    max_uses=1,
                    expires_at=now + DIRECT_INVITE_TTL,
                )
            else:
                token = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
                row = GroupInvitation(
                    group_id=group_id,
                    kind=InvitationKind.LINK,
                    token_hash=_token_hash(token),
                    created_by=user_id,
                    max_uses=request.max_uses,
                    expires_at=now + timedelta(hours=request.expires_in_hours),
                )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            if row.kind == InvitationKind.DIRECT:
                platform.record_event(
                    session,
                    aggregate_type="group",
                    aggregate_id=group_id,
                    event_type="group.invited",
                    payload={
                        "group_id": str(group_id),
                        "invitation_id": str(row.id),
                        "inviter_id": str(user_id),
                        "invitee_id": str(row.invitee_user_id),
                    },
                )
            [out] = await self._invitations_out(session, [row])
        return CreatedGroupInvitation(
            invitation=out,
            token=token,
            url=f"{self._site}/invite#t={token}" if token else None,
        )

    async def group_invitations(
        self, user_id: uuid.UUID, group_id: uuid.UUID, *, cursor: str | None, limit: int
    ) -> GroupInvitationPage:
        scope = f"group-invitations.{group_id}"
        async with self._sessionmaker() as session:
            context = await self._context(session, group_id, user_id)
            role = context.role
            assert role is not None
            if Permission.MEMBERS_INVITE not in permissions(
                role, members_can_invite=False, premium_active=True
            ):
                raise _forbidden()
            conditions = [GroupInvitation.group_id == group_id]
            if cursor:
                position = self._cursors.decode(cursor, scope=scope)
                conditions.append(GroupInvitation.id < uuid.UUID(str(position["id"])))
            rows = list(
                await session.scalars(
                    select(GroupInvitation)
                    .where(*conditions)
                    .order_by(GroupInvitation.id.desc())
                    .limit(limit + 1)
                )
            )
            has_more = len(rows) > limit
            rows = rows[:limit]
            data = await self._invitations_out(session, rows)
        next_cursor = (
            self._cursors.encode({"id": str(rows[-1].id)}, scope=scope)
            if has_more and rows
            else None
        )
        return GroupInvitationPage(
            data=data, page=PageInfo(next_cursor=next_cursor, has_more=has_more)
        )

    async def revoke_invitation(
        self, user_id: uuid.UUID, group_id: uuid.UUID, invitation_id: uuid.UUID
    ) -> None:
        async with self._sessionmaker() as session, session.begin():
            context = await self._context(session, group_id, user_id)
            row = await session.get(GroupInvitation, invitation_id, with_for_update=True)
            if row is None or row.group_id != group_id:
                raise AppError(ErrorCode.NOT_FOUND, "Invitation not found.")
            role = context.role
            assert role is not None
            admin = Permission.MEMBERS_INVITE in permissions(
                role, members_can_invite=False, premium_active=True
            )
            if not admin and row.created_by != user_id:
                raise _forbidden()
            if row.status == InvitationStatus.ACTIVE:
                row.status = InvitationStatus.REVOKED
                row.revoked_at = self._clock.now()
                row.revoked_by = user_id

    async def my_invitations(
        self, user_id: uuid.UUID, *, cursor: str | None, limit: int
    ) -> GroupInvitationPage:
        scope = f"my-group-invitations.{user_id}"
        conditions = [
            GroupInvitation.invitee_user_id == user_id,
            GroupInvitation.status == InvitationStatus.ACTIVE,
            GroupInvitation.expires_at > func.now(),
        ]
        async with self._sessionmaker() as session:
            hidden = await trust_safety.blocked_ids(session, user_id)
            if hidden:
                conditions.append(
                    or_(
                        GroupInvitation.created_by.is_(None),
                        GroupInvitation.created_by.not_in(hidden),
                    )
                )
            if cursor:
                position = self._cursors.decode(cursor, scope=scope)
                conditions.append(GroupInvitation.id < uuid.UUID(str(position["id"])))
            rows = list(
                await session.scalars(
                    select(GroupInvitation)
                    .where(*conditions)
                    .order_by(GroupInvitation.id.desc())
                    .limit(limit + 1)
                )
            )
            has_more = len(rows) > limit
            rows = rows[:limit]
            data = await self._invitations_out(session, rows)
        next_cursor = (
            self._cursors.encode({"id": str(rows[-1].id)}, scope=scope)
            if has_more and rows
            else None
        )
        return GroupInvitationPage(
            data=data, page=PageInfo(next_cursor=next_cursor, has_more=has_more)
        )

    async def respond(
        self, user_id: uuid.UUID, invitation_id: uuid.UUID, *, accept: bool
    ) -> GroupMemberOut | None:
        """Accept or decline a direct invitation (joining is free, GRP-008)."""
        now = self._clock.now()
        async with self._sessionmaker() as session, session.begin():
            row = await session.get(GroupInvitation, invitation_id, with_for_update=True)
            if row is None or row.invitee_user_id != user_id:
                raise AppError(ErrorCode.NOT_FOUND, "Invitation not found.")
            if row.status != InvitationStatus.ACTIVE or row.expires_at <= now:
                raise AppError(
                    ErrorCode.INVITATION_INVALID, "This invitation is no longer valid.", status=409
                )
            if not accept:
                row.status = InvitationStatus.DECLINED
                return None
            group = await session.get(TravelGroup, row.group_id, with_for_update=True)
            settings = await session.get(GroupSettings, row.group_id)
            assert group is not None
            assert settings is not None
            membership, _ = await self._join(
                session, group, settings, user_id, invited_by=row.created_by
            )
            row.status = InvitationStatus.ACCEPTED
            row.use_count = 1
            [out] = await self._members_out(session, [membership])
            return out

    async def _link(self, session: AsyncSession, token: str, *, lock: bool) -> GroupInvitation:
        query = select(GroupInvitation).where(
            GroupInvitation.token_hash == _token_hash(token),
            GroupInvitation.kind == InvitationKind.LINK,
        )
        row = await session.scalar(query.with_for_update() if lock else query)
        if (
            row is None
            or row.status != InvitationStatus.ACTIVE
            or row.expires_at <= self._clock.now()
            or row.use_count >= row.max_uses
        ):
            # Unknown, expired, revoked or exhausted: deliberately indistinguishable.
            raise AppError(
                ErrorCode.INVITATION_INVALID, "This invitation link isn't valid.", status=409
            )
        return row

    async def preview(self, user_id: uuid.UUID, token: str) -> GroupInvitationPreview:
        async with self._sessionmaker() as session:
            row = await self._link(session, token, lock=False)
            group = await session.get(TravelGroup, row.group_id)
            assert group is not None
            if group.status != GroupStatus.ACTIVE:
                raise AppError(
                    ErrorCode.INVITATION_INVALID, "This invitation link isn't valid.", status=409
                )
            summary = (await self._summaries(session, [group]))[group.id]
            inviter = None
            if row.created_by:
                found = (await profiles.authors(session, [row.created_by])).get(row.created_by)
                inviter = profiles.user_summary(found) if found else None
            member = await session.scalar(
                select(GroupMembership.status).where(
                    GroupMembership.group_id == group.id, GroupMembership.user_id == user_id
                )
            )
            return GroupInvitationPreview(
                group=summary,
                inviter=inviter,
                expires_at=row.expires_at,
                is_member=member in _MEMBER,
            )

    async def redeem(self, user_id: uuid.UUID, token: str) -> GroupMemberOut:
        """Lock the invitation, then check status, expiry, uses and capacity together (T-GRP-02)."""
        async with self._sessionmaker() as session, session.begin():
            row = await self._link(session, token, lock=True)
            group = await session.get(TravelGroup, row.group_id, with_for_update=True)
            settings = await session.get(GroupSettings, row.group_id)
            assert group is not None
            assert settings is not None
            if row.created_by and await trust_safety.is_blocked(session, user_id, row.created_by):
                raise AppError(
                    ErrorCode.INVITATION_INVALID, "This invitation link isn't valid.", status=409
                )
            membership, joined = await self._join(
                session, group, settings, user_id, invited_by=row.created_by
            )
            if joined:  # already a member: no use consumed
                row.use_count += 1
                if row.use_count >= row.max_uses:
                    row.status = InvitationStatus.EXHAUSTED
            [out] = await self._members_out(session, [membership])
            return out

    # ─────────────────────────────── ownership ───────────────────────────────

    async def _transfer_out(
        self, session: AsyncSession, row: GroupOwnershipTransfer
    ) -> OwnershipTransferOut:
        users = await profiles.authors(session, [row.from_user_id, row.to_user_id])
        return OwnershipTransferOut(
            id=row.id,
            group_id=row.group_id,
            from_user=profiles.user_summary(users[row.from_user_id]),
            to_user=profiles.user_summary(users[row.to_user_id]),
            status=row.status,  # type: ignore[arg-type]
            created_at=row.created_at,
            expires_at=row.expires_at,
            responded_at=row.responded_at,
        )

    async def offer_transfer(
        self, user_id: uuid.UUID, group_id: uuid.UUID, to_user_id: uuid.UUID
    ) -> OwnershipTransferOut:
        """Always allowed for the owner, even after a lapse (docs/07 §5)."""
        now = self._clock.now()
        async with self._sessionmaker() as session, session.begin():
            context = await self._context(session, group_id, user_id, lock=True)
            if context.role is not Role.OWNER:
                raise _forbidden("Only the owner can transfer the group.")
            target = await session.scalar(
                select(GroupMembership).where(
                    GroupMembership.group_id == group_id,
                    GroupMembership.user_id == to_user_id,
                    GroupMembership.status.in_(_MEMBER),
                )
            )
            if target is None or to_user_id == user_id:
                raise AppError(ErrorCode.NOT_FOUND, "Member not found.")
            await session.execute(
                update(GroupOwnershipTransfer)
                .where(
                    GroupOwnershipTransfer.group_id == group_id,
                    GroupOwnershipTransfer.status == TransferStatus.PENDING,
                )
                .values(status=TransferStatus.CANCELLED, responded_at=func.now())
            )
            row = GroupOwnershipTransfer(
                group_id=group_id,
                from_user_id=user_id,
                to_user_id=to_user_id,
                expires_at=now + TRANSFER_TTL,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return await self._transfer_out(session, row)

    async def answer_transfer(
        self, user_id: uuid.UUID, group_id: uuid.UUID, transfer_id: uuid.UUID, action: str
    ) -> OwnershipTransferOut:
        now = self._clock.now()
        async with self._sessionmaker() as session, session.begin():
            group = await session.get(TravelGroup, group_id, with_for_update=True)
            row = await session.get(GroupOwnershipTransfer, transfer_id, with_for_update=True)
            if group is None or row is None or row.group_id != group_id:
                raise AppError(ErrorCode.NOT_FOUND, "Transfer not found.")
            party = row.from_user_id if action == "cancel" else row.to_user_id
            if party != user_id:
                raise AppError(ErrorCode.NOT_FOUND, "Transfer not found.")
            if row.status != TransferStatus.PENDING or row.expires_at <= now:
                raise AppError(ErrorCode.CONFLICT, "This transfer is no longer pending.")
            row.responded_at = now
            if action == "accept":
                old = await self._target(session, group_id, row.from_user_id)
                new = await self._target(session, group_id, row.to_user_id)
                old.role = Role.ADMIN
                await session.flush()  # one owner at a time (partial unique index)
                new.role = Role.OWNER
                group.owner_id = row.to_user_id
                group.version += 1
                row.status = TransferStatus.ACCEPTED
                platform.record_event(
                    session,
                    aggregate_type="group",
                    aggregate_id=group_id,
                    event_type="group.ownership_transferred",
                    payload={
                        "group_id": str(group_id),
                        "from_user_id": str(row.from_user_id),
                        "to_user_id": str(row.to_user_id),
                    },
                )
            else:
                row.status = (
                    TransferStatus.DECLINED if action == "decline" else TransferStatus.CANCELLED
                )
            await session.flush()
            return await self._transfer_out(session, row)

    # ─────────────────────────────── announcements ───────────────────────────────

    async def announce(
        self,
        principal: Principal,
        group_id: uuid.UUID,
        *,
        client_message_id: uuid.UUID,
        body: str,
        pin: bool,
    ) -> dict[str, Any]:
        async with self._sessionmaker() as session:
            context = await self._context(session, group_id, principal.user_id)
            if Permission.ANNOUNCEMENTS_POST not in context.permissions():
                raise _forbidden("Only admins can post announcements.")
            if context.group.status != GroupStatus.ACTIVE:
                raise AppError(ErrorCode.CONFLICT, "This group is archived.")
            conversation_id = context.group.conversation_id
        if self._announce is None or conversation_id is None:
            raise AppError(ErrorCode.SERVICE_UNAVAILABLE, "Announcements aren't available.")
        return await self._announce(principal, conversation_id, client_message_id, body, pin)


# ─────────────────────────────── for other modules ───────────────────────────────


async def chat_policy(
    session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID, *, now: datetime
) -> ChatPolicy:
    """Send rights and chat permissions of one member (GCHAT-002/003/004), for messaging."""
    group = await session.get(TravelGroup, group_id)
    membership = await session.scalar(
        select(GroupMembership).where(
            GroupMembership.group_id == group_id, GroupMembership.user_id == user_id
        )
    )
    if group is None or membership is None or membership.status not in _MEMBER:
        return ChatPolicy(restriction="member_restricted", permissions=frozenset(), title=None)
    settings = await session.get(GroupSettings, group_id)
    status = await billing.group_premium(session, group.owner_id, at=now)
    role = Role(membership.role)
    granted = permissions(
        role,
        members_can_invite=bool(settings and settings.members_can_invite),
        premium_active=status.premium_features_active,
    )
    restriction: str | None = None
    if group.status != GroupStatus.ACTIVE:
        restriction = "archived"
    elif membership.status == MembershipStatus.RESTRICTED and (
        membership.restricted_until is None or membership.restricted_until > now
    ):
        restriction = "member_restricted"
    elif (
        settings is not None
        and settings.chat_mode == "admins_only"
        and RANK[role] < RANK[Role.ADMIN]
    ):
        restriction = "chat_admins_only"
    return ChatPolicy(
        restriction=restriction,
        permissions=frozenset(p.value for p in granted),
        title=group.name,
    )


async def is_group_member(session: AsyncSession, group_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    status = await session.scalar(
        select(GroupMembership.status).where(
            and_(GroupMembership.group_id == group_id, GroupMembership.user_id == user_id)
        )
    )
    return status in _MEMBER


async def hand_over_owned_groups(session: AsyncSession, owner_id: uuid.UUID) -> None:
    """Before an owner's account is erased (docs/07 §5): each group passes to its longest-tenured
    admin, then moderator, then member; a group nobody is left in is archived, never deleted."""
    groups = (
        await session.scalars(
            select(TravelGroup).where(TravelGroup.owner_id == owner_id).with_for_update()
        )
    ).all()
    for group in groups:
        candidates = (
            await session.scalars(
                select(GroupMembership).where(
                    GroupMembership.group_id == group.id,
                    GroupMembership.user_id != owner_id,
                    GroupMembership.status.in_(_MEMBER),
                )
            )
        ).all()
        heir = min(
            candidates,
            key=lambda m: (-RANK[Role(m.role)], m.joined_at),
            default=None,
        )
        old = await session.scalar(
            select(GroupMembership).where(
                GroupMembership.group_id == group.id, GroupMembership.user_id == owner_id
            )
        )
        if old is not None:
            old.role = Role.ADMIN  # the row goes with the account; frees the one-owner index
            await session.flush()
        if heir is None:
            group.status = GroupStatus.ARCHIVED
            group.archived_at = func.now()
        else:
            heir.role = Role.OWNER
            group.owner_id = heir.user_id
            platform.record_event(
                session,
                aggregate_type="group",
                aggregate_id=group.id,
                event_type="group.ownership_transferred",
                payload={
                    "group_id": str(group.id),
                    "from_user_id": str(owner_id),
                    "to_user_id": str(heir.user_id),
                    "reason": "owner_account_deleted",
                },
            )
        group.version += 1
        await session.flush()


async def purge_expired(session: AsyncSession) -> int:
    """Mark expired invitations and pending transfers (rows are kept for the group's history)."""
    invitations = await session.execute(
        update(GroupInvitation)
        .where(
            GroupInvitation.status == InvitationStatus.ACTIVE,
            GroupInvitation.expires_at <= func.now(),
        )
        .values(status=InvitationStatus.EXPIRED)
    )
    transfers = await session.execute(
        update(GroupOwnershipTransfer)
        .where(
            GroupOwnershipTransfer.status == TransferStatus.PENDING,
            GroupOwnershipTransfer.expires_at <= func.now(),
        )
        .values(status=TransferStatus.EXPIRED)
    )
    return int(getattr(invitations, "rowcount", 0) or 0) + int(
        getattr(transfers, "rowcount", 0) or 0
    )
