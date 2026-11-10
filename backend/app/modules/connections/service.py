"""Connection requests and connections (BL-2.04; CONN-001..009).

Rules on sending, checked in this order:
- verified email, no ``connection_requests_limited`` restriction;
- recipient exists and is active (otherwise ``404``);
- no block either way and the recipient's ``connection_requests_from`` allows it — both refused
  with the same generic ``403 connection_request_not_allowed`` so the reason isn't revealed;
- not already connected (``409 already_connected``), no pending request either way (``409``);
- no decline from the recipient within 30 days (``409 connection_request_cooldown``);
- accounts younger than 7 days send at most 5 a day (``429``), on top of the route's
  ``contact`` rate limit.

"Shared context" counts only what both travellers chose to share: being visible in discovery in
the same city, sharing an upcoming trip to the same destination for discovery, or an active
travel group (registered with ``add_shared_context`` from main.py). Private signals (browse
destination, unshared trips, invisible discovery) never count: ``can_request_connection`` is
shown on profiles, so they would leak through it (T-LOC-03, T-LOC-08).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.pagination import CursorCodec, Page, PageInfo
from app.core.security.principal import Principal
from app.core.time import Clock
from app.modules.connections.domain import (
    DECLINE_COOLDOWN,
    NEW_ACCOUNT_AGE,
    NEW_ACCOUNT_DAILY_LIMIT,
    REQUEST_TTL,
    Action,
    Actor,
    InvalidTransitionError,
    Relationship,
    RelationshipFacts,
    RequestStatus,
    ordered_pair,
    policy_allows,
    relationship,
    transition,
)
from app.modules.connections.models import ConnectionRequest, UserConnection
from app.modules.connections.schemas import (
    ConnectionOut,
    ConnectionRequestOut,
    CreateConnectionRequestRequest,
)
from app.modules.identity import service as identity
from app.modules.location import service as location
from app.modules.platform import service as platform
from app.modules.profiles import service as profiles
from app.modules.trust_safety import service as trust_safety

REQUEST_ROUTE = "POST /v1/connections/requests"


def _not_allowed() -> AppError:
    return AppError(
        ErrorCode.CONNECTION_REQUEST_NOT_ALLOWED, "You can't send this person a request."
    )


def _not_found() -> AppError:
    return AppError(ErrorCode.NOT_FOUND, "Request not found.")


def _pair(a: uuid.UUID, b: uuid.UUID) -> ColumnElement[bool]:
    low, high = ordered_pair(a, b)
    return and_(UserConnection.user_low_id == low, UserConnection.user_high_id == high)


async def _connected(session: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> bool:
    return (
        await session.scalar(select(func.count()).select_from(UserConnection).where(_pair(a, b)))
    ) == 1


async def _expire_stale(session: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> None:
    """Pending requests past their expiry become ``expired`` (CONN-007)."""
    await session.execute(
        update(ConnectionRequest)
        .where(
            ConnectionRequest.status == RequestStatus.PENDING,
            ConnectionRequest.expires_at <= func.now(),
            or_(
                and_(ConnectionRequest.requester_id == a, ConnectionRequest.recipient_id == b),
                and_(ConnectionRequest.requester_id == b, ConnectionRequest.recipient_id == a),
            ),
        )
        .values(status=RequestStatus.EXPIRED)
    )


SharedContext = Callable[[AsyncSession, uuid.UUID, uuid.UUID], Awaitable[bool]]
_EXTRA_CONTEXTS: list[SharedContext] = []


def add_shared_context(check: SharedContext) -> None:
    """Let a higher-layer feature (travel groups) count as a shared context (CONN-004). The
    module boundaries forbid importing it here, so main.py registers it; idempotent."""
    if check not in _EXTRA_CONTEXTS:
        _EXTRA_CONTEXTS.append(check)


async def _shared_context(session: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> bool:
    a_city = await location.visible_discovery_destination(session, a)
    if a_city is not None and a_city == await location.visible_discovery_destination(session, b):
        return True  # both visible in discovery in the same city
    if await location.share_upcoming_destination(session, a, b):
        return True  # both share an upcoming trip there for discovery
    for check in _EXTRA_CONTEXTS:
        if await check(session, a, b):
            return True
    return False


async def _facts(
    session: AsyncSession, viewer: uuid.UUID, other: uuid.UUID, now: datetime
) -> RelationshipFacts:
    pending = (
        (
            await session.execute(
                select(ConnectionRequest.requester_id).where(
                    ConnectionRequest.status == RequestStatus.PENDING,
                    ConnectionRequest.expires_at > func.now(),
                    or_(
                        and_(
                            ConnectionRequest.requester_id == viewer,
                            ConnectionRequest.recipient_id == other,
                        ),
                        and_(
                            ConnectionRequest.requester_id == other,
                            ConnectionRequest.recipient_id == viewer,
                        ),
                    ),
                )
            )
        )
        .scalars()
        .all()
    )
    declined = await session.scalar(
        select(func.count())
        .select_from(ConnectionRequest)
        .where(
            ConnectionRequest.requester_id == viewer,
            ConnectionRequest.recipient_id == other,
            ConnectionRequest.status == RequestStatus.DECLINED,
            ConnectionRequest.responded_at > now - DECLINE_COOLDOWN,
        )
    )
    return RelationshipFacts(
        blocked=await trust_safety.is_blocked(session, viewer, other),
        connected=await _connected(session, viewer, other),
        outgoing_pending=viewer in pending,
        incoming_pending=other in pending,
        declined_within_cooldown=bool(declined),
    )


async def relationship_between(
    session: AsyncSession, viewer: uuid.UUID, other: uuid.UUID, now: datetime
) -> tuple[str, bool]:
    """(relationship state, whether the viewer may send a request) for ``PublicProfile``."""
    if viewer == other:
        return Relationship.NONE, False
    state = relationship(await _facts(session, viewer, other, now))
    can_request = state is Relationship.NONE and policy_allows(
        await profiles.connection_policy(session, other),
        shared_context=await _shared_context(session, viewer, other),
    )
    return state, can_request


@dataclass(frozen=True, slots=True)
class RelationshipDetail:
    """For ``GET /v1/users/{id}/relationship`` (CONN-001)."""

    state: str
    can_request: bool
    pending_request_id: uuid.UUID | None
    cooldown_until: datetime | None


async def relationship_detail(
    session: AsyncSession, viewer: uuid.UUID, other: uuid.UUID, now: datetime
) -> RelationshipDetail:
    state, can_request = await relationship_between(session, viewer, other, now)
    if viewer == other:
        return RelationshipDetail(state, can_request, None, None)
    pending = await session.scalar(
        select(ConnectionRequest.id)
        .where(
            ConnectionRequest.status == RequestStatus.PENDING,
            ConnectionRequest.expires_at > now,
            or_(
                and_(
                    ConnectionRequest.requester_id == viewer,
                    ConnectionRequest.recipient_id == other,
                ),
                and_(
                    ConnectionRequest.requester_id == other,
                    ConnectionRequest.recipient_id == viewer,
                ),
            ),
        )
        .limit(1)
    )
    declined_at = await session.scalar(
        select(func.max(ConnectionRequest.responded_at)).where(
            ConnectionRequest.requester_id == viewer,
            ConnectionRequest.recipient_id == other,
            ConnectionRequest.status == RequestStatus.DECLINED,
        )
    )
    cooldown = declined_at + DECLINE_COOLDOWN if declined_at is not None else None
    return RelationshipDetail(
        state=state,
        can_request=can_request,
        pending_request_id=pending,
        cooldown_until=cooldown if cooldown is not None and cooldown > now else None,
    )


async def end_between(session: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> None:
    """Block hook (CONN-009): the connection and any pending requests end, silently."""
    await session.execute(delete(UserConnection).where(_pair(a, b)))
    await session.execute(
        update(ConnectionRequest)
        .where(
            ConnectionRequest.status == RequestStatus.PENDING,
            or_(
                and_(ConnectionRequest.requester_id == a, ConnectionRequest.recipient_id == b),
                and_(ConnectionRequest.requester_id == b, ConnectionRequest.recipient_id == a),
            ),
        )
        .values(status=RequestStatus.CANCELLED, responded_at=func.now())
    )


async def _request_out(
    session: AsyncSession, rows: Sequence[ConnectionRequest]
) -> list[ConnectionRequestOut]:
    users = await profiles.authors(
        session, list({u for r in rows for u in (r.requester_id, r.recipient_id)})
    )
    return [
        ConnectionRequestOut.model_validate(
            {
                "id": r.id,
                "requester": profiles.user_summary(users[r.requester_id]),
                "recipient": profiles.user_summary(users[r.recipient_id]),
                "status": r.status,
                "context": r.context,
                "note": r.note,
                "created_at": r.created_at,
                "responded_at": r.responded_at,
                "expires_at": r.expires_at,
            }
        )
        for r in rows
        if r.requester_id in users and r.recipient_id in users
    ]


class ConnectionService:
    def __init__(
        self, *, sessionmaker: async_sessionmaker[AsyncSession], cursors: CursorCodec, clock: Clock
    ) -> None:
        self._sessionmaker = sessionmaker
        self._cursors = cursors
        self._clock = clock

    async def create_request(
        self,
        principal: Principal,
        request: CreateConnectionRequestRequest,
        *,
        idempotency_key: uuid.UUID,
    ) -> tuple[ConnectionRequestOut, bool]:
        me, them = principal.user_id, request.recipient_id
        if not principal.email_verified:
            raise AppError(
                ErrorCode.EMAIL_UNVERIFIED, "Verify your email to connect with travellers."
            )
        if me == them:
            raise AppError(
                ErrorCode.VALIDATION_FAILED,
                "You can't connect with yourself.",
                errors=[FieldError(field="/recipient_id", code="invalid", message="That's you.")],
            )
        now = self._clock.now()
        async with self._sessionmaker() as session, session.begin():
            replay = await platform.idempotency.claim(
                session,
                user_id=me,
                key=idempotency_key,
                route=REQUEST_ROUTE,
                payload=request.model_dump(mode="json"),
            )
            if replay is not None:
                return ConnectionRequestOut.model_validate(replay.body), True
            await trust_safety.ensure_not_restricted(
                session,
                me,
                "connection_requests_limited",
                message="Connection requests are limited on your account right now.",
            )
            if not await identity.is_active(session, them):
                raise AppError(ErrorCode.NOT_FOUND, "Traveller not found.")
            if await trust_safety.is_blocked(session, me, them):
                raise _not_allowed()
            policy = await profiles.connection_policy(session, them)
            if not policy_allows(policy, shared_context=await _shared_context(session, me, them)):
                raise _not_allowed()
            if await _connected(session, me, them):
                raise AppError(ErrorCode.ALREADY_CONNECTED, "You're already connected.")
            await _expire_stale(session, me, them)
            facts = await _facts(session, me, them, now)
            if facts.outgoing_pending:
                raise AppError(ErrorCode.CONFLICT, "You already sent a request.")
            if facts.incoming_pending:
                raise AppError(
                    ErrorCode.CONFLICT,
                    "They already asked to connect with you. Accept their request.",
                )
            if facts.declined_within_cooldown:
                raise AppError(
                    ErrorCode.CONNECTION_REQUEST_COOLDOWN, "Wait before asking this person again."
                )
            created = await identity.account_created_at(session, me)
            if created is not None and now - created < NEW_ACCOUNT_AGE:
                sent = await session.scalar(
                    select(func.count())
                    .select_from(ConnectionRequest)
                    .where(
                        ConnectionRequest.requester_id == me,
                        ConnectionRequest.created_at > func.now() - timedelta(days=1),
                    )
                )
                if (sent or 0) >= NEW_ACCOUNT_DAILY_LIMIT:
                    raise AppError(
                        ErrorCode.RATE_LIMITED,
                        "New accounts can send a few requests a day. Try again tomorrow.",
                        headers={"Retry-After": "3600"},
                    )
            row = ConnectionRequest(
                requester_id=me,
                recipient_id=them,
                status=RequestStatus.PENDING,
                context=request.context,
                context_ref_id=request.context_ref_id,
                note=(request.note or "").strip() or None,
                expires_at=now + REQUEST_TTL,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            platform.record_event(
                session,
                aggregate_type="connection_request",
                aggregate_id=row.id,
                event_type="connection.requested",
                payload={
                    "request_id": str(row.id),
                    "requester_id": str(me),
                    "recipient_id": str(them),
                },
            )
            [out] = await _request_out(session, [row])
            await platform.idempotency.complete(
                session,
                user_id=me,
                key=idempotency_key,
                status=201,
                body=out.model_dump(mode="json"),
            )
        return out, False

    async def list_requests(
        self,
        user_id: uuid.UUID,
        *,
        direction: str,
        status: str,
        cursor: str | None,
        limit: int,
    ) -> Page[ConnectionRequestOut]:
        scope = f"connection_requests.{user_id}.{direction}.{status}"
        mine = (
            ConnectionRequest.recipient_id
            if direction == "incoming"
            else ConnectionRequest.requester_id
        )
        conditions = [mine == user_id, ConnectionRequest.status == status]
        if status == RequestStatus.PENDING:
            conditions.append(ConnectionRequest.expires_at > func.now())
        async with self._sessionmaker() as session:
            hidden = await trust_safety.blocked_ids(session, user_id)
            other = (
                ConnectionRequest.requester_id
                if direction == "incoming"
                else ConnectionRequest.recipient_id
            )
            if hidden:
                conditions.append(other.not_in(hidden))
            if cursor:
                position = self._cursors.decode(cursor, scope=scope)
                conditions.append(ConnectionRequest.id < uuid.UUID(str(position["id"])))
            rows = list(
                (
                    await session.scalars(
                        select(ConnectionRequest)
                        .where(*conditions)
                        .order_by(ConnectionRequest.id.desc())
                        .limit(limit + 1)
                    )
                ).all()
            )
            has_more = len(rows) > limit
            rows = rows[:limit]
            data = await _request_out(session, rows)
        next_cursor = (
            self._cursors.encode({"id": str(rows[-1].id)}, scope=scope)
            if has_more and rows
            else None
        )
        return Page[ConnectionRequestOut](
            data=data, page=PageInfo(next_cursor=next_cursor, has_more=has_more)
        )

    async def respond(
        self, user_id: uuid.UUID, request_id: uuid.UUID, action: Action
    ) -> ConnectionOut | None:
        """Accept (returns the connection), decline or cancel a pending request."""
        now = self._clock.now()
        actor = Actor.REQUESTER if action is Action.CANCEL else Actor.RECIPIENT
        expired = False
        connection: ConnectionOut | None = None
        async with self._sessionmaker() as session, session.begin():
            row = await session.get(ConnectionRequest, request_id, with_for_update=True)
            party = None
            if row is not None:
                party = row.requester_id if actor is Actor.REQUESTER else row.recipient_id
            if row is None or party != user_id:
                raise _not_found()
            try:
                status = transition(
                    RequestStatus(row.status), action, actor, expires_at=row.expires_at, now=now
                )
            except InvalidTransitionError as exc:
                if row.status != RequestStatus.PENDING or now < row.expires_at:
                    raise AppError(
                        ErrorCode.CONFLICT, "This request is no longer pending."
                    ) from exc
                status = RequestStatus.EXPIRED  # recorded, then reported after the commit
            row.status = status
            if status is RequestStatus.EXPIRED:
                expired = True
            else:
                row.responded_at = now
            if status is not RequestStatus.ACCEPTED:
                connection = None
            else:
                connection = await self._connect(session, row, now)
        if expired:
            raise AppError(ErrorCode.CONFLICT, "This request has expired.")
        return connection

    async def _connect(
        self, session: AsyncSession, row: ConnectionRequest, now: datetime
    ) -> ConnectionOut:
        low, high = ordered_pair(row.requester_id, row.recipient_id)
        await session.execute(
            insert(UserConnection)
            .values(user_low_id=low, user_high_id=high, source_request_id=row.id, connected_at=now)
            .on_conflict_do_nothing(
                index_elements=[UserConnection.user_low_id, UserConnection.user_high_id]
            )
        )
        platform.record_event(
            session,
            aggregate_type="connection_request",
            aggregate_id=row.id,
            event_type="connection.accepted",
            payload={
                "request_id": str(row.id),
                "requester_id": str(row.requester_id),
                "recipient_id": str(row.recipient_id),
            },
        )
        other = (await profiles.authors(session, [row.requester_id]))[row.requester_id]
        return ConnectionOut(user=profiles.user_summary(other), connected_at=now)

    async def list_connections(
        self, user_id: uuid.UUID, *, cursor: str | None, limit: int
    ) -> Page[ConnectionOut]:
        scope = f"connections.{user_id}"
        conditions = [
            or_(UserConnection.user_low_id == user_id, UserConnection.user_high_id == user_id)
        ]
        async with self._sessionmaker() as session:
            if cursor:
                position = self._cursors.decode(cursor, scope=scope)
                at = datetime.fromisoformat(str(position["at"]))
                conditions.append(UserConnection.connected_at < at)
            rows = list(
                (
                    await session.scalars(
                        select(UserConnection)
                        .where(*conditions)
                        .order_by(UserConnection.connected_at.desc())
                        .limit(limit + 1)
                    )
                ).all()
            )
            has_more = len(rows) > limit
            rows = rows[:limit]
            others = [r.user_high_id if r.user_low_id == user_id else r.user_low_id for r in rows]
            users = await profiles.authors(session, others)
        data = [
            ConnectionOut(user=profiles.user_summary(users[o]), connected_at=r.connected_at)
            for r, o in zip(rows, others, strict=True)
            if o in users
        ]
        next_cursor = (
            self._cursors.encode({"at": rows[-1].connected_at.isoformat()}, scope=scope)
            if has_more and rows
            else None
        )
        return Page[ConnectionOut](
            data=data, page=PageInfo(next_cursor=next_cursor, has_more=has_more)
        )

    async def remove(self, user_id: uuid.UUID, other_id: uuid.UUID) -> None:
        """Silent and idempotent (CONN-008)."""
        async with self._sessionmaker() as session, session.begin():
            await session.execute(delete(UserConnection).where(_pair(user_id, other_id)))


async def purge_expired(session: AsyncSession) -> int:
    """Expire stale pending requests; drop answered requests after a year."""
    expired = await session.execute(
        update(ConnectionRequest)
        .where(
            ConnectionRequest.status == RequestStatus.PENDING,
            ConnectionRequest.expires_at <= func.now(),
        )
        .values(status=RequestStatus.EXPIRED)
    )
    return int(getattr(expired, "rowcount", 0) or 0) + await platform.delete_batch(
        session,
        ConnectionRequest,
        (ConnectionRequest.status != RequestStatus.PENDING)
        & (ConnectionRequest.created_at < platform.ago(days=365)),
    )


async def declined_requesters(session: AsyncSession, viewer: uuid.UUID) -> set[uuid.UUID]:
    """People whose requests the viewer declined in the last 30 days (deprioritized, DISC-008)."""
    rows = await session.scalars(
        select(ConnectionRequest.requester_id).where(
            ConnectionRequest.recipient_id == viewer,
            ConnectionRequest.status == RequestStatus.DECLINED,
            ConnectionRequest.responded_at > func.now() - DECLINE_COOLDOWN,
        )
    )
    return set(rows)


async def request_stats_since(
    session: AsyncSession, *, hours: int, at_least: int
) -> dict[uuid.UUID, tuple[int, int]]:
    """Requesters with ``at_least`` requests in the window: (sent, declined)."""
    declined = func.count().filter(ConnectionRequest.status == RequestStatus.DECLINED)
    rows = await session.execute(
        select(ConnectionRequest.requester_id, func.count(), declined)
        .where(ConnectionRequest.created_at > func.now() - timedelta(hours=hours))
        .group_by(ConnectionRequest.requester_id)
        .having(func.count() >= at_least)
    )
    return {requester: (sent, refused) for requester, sent, refused in rows.all()}


async def connected_since(session: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> datetime | None:
    """When ``a`` and ``b`` connected, or None (new-connection message filter, SAFE-006)."""
    low, high = sorted((a, b))
    found: datetime | None = await session.scalar(
        select(UserConnection.connected_at).where(
            UserConnection.user_low_id == low, UserConnection.user_high_id == high
        )
    )
    return found


async def connected_ids(
    session: AsyncSession, user_id: uuid.UUID, others: Sequence[uuid.UUID]
) -> set[uuid.UUID]:
    """Which of ``others`` are connected with ``user_id`` (messaging re-checks on every send)."""
    if not others:
        return set()
    rows = await session.execute(
        select(UserConnection.user_low_id, UserConnection.user_high_id).where(
            or_(
                and_(
                    UserConnection.user_low_id == user_id,
                    UserConnection.user_high_id.in_(set(others)),
                ),
                and_(
                    UserConnection.user_high_id == user_id,
                    UserConnection.user_low_id.in_(set(others)),
                ),
            )
        )
    )
    return {high if low == user_id else low for low, high in rows.all()}


async def export_user_data(
    session: AsyncSession, user_id: uuid.UUID
) -> dict[str, list[dict[str, object]]]:
    """Personal-data export (BL-6.03; AUTH-011): what this module holds about the user."""
    from sqlalchemy import or_ as either

    from app.modules.connections.models import ConnectionRequest, UserConnection

    return {
        "connection_requests": await platform.export_rows(
            session,
            ConnectionRequest,
            either(
                ConnectionRequest.requester_id == user_id,
                ConnectionRequest.recipient_id == user_id,
            ),
        ),
        "connections": await platform.export_rows(
            session,
            UserConnection,
            either(UserConnection.user_low_id == user_id, UserConnection.user_high_id == user_id),
        ),
    }
