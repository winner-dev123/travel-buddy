"""Notification center (BL-1.16, NOTIF-001).

Notifications are created from domain events (outbox → job), never inline in the request that
caused them. ``notify`` skips self-notifications, types the recipient turned off for ``in_app`` and
actors in a block relationship with the recipient. Each row carries a dedupe key so redelivered
events and repeated actions (react, un-react, react again) notify once.

Reading hides notifications whose actor is now blocked either way, renders title and body in the
reader's locale and resolves the actor's current public identity.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from app.core.pagination import CursorCodec, PageInfo
from app.modules.identity import service as identity
from app.modules.notifications import push
from app.modules.notifications.domain import moderation_variant, render
from app.modules.notifications.models import Notification
from app.modules.notifications.push import PushSender
from app.modules.notifications.schemas import NotificationOut, NotificationPage
from app.modules.platform import service as platform
from app.modules.profiles import service as profiles
from app.modules.trust_safety import service as trust_safety

JOB_KIND = "notifications.from_event"
PUSH_JOB = "notifications.push"


async def notify(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: str,
    dedupe_key: str,
    actor_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    payload: Mapping[str, Any] | None = None,
) -> bool:
    """Create a notification unless suppressed; True when a new row was written."""
    if actor_id is not None and actor_id == user_id:
        return False
    if not await profiles.wants_notification(session, user_id, kind):
        return False
    if actor_id is not None and await trust_safety.is_blocked(session, user_id, actor_id):
        return False
    inserted = await session.execute(
        insert(Notification)
        .values(
            user_id=user_id,
            type=kind,
            actor_id=actor_id,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=dict(payload or {}),
            dedupe_key=dedupe_key,
        )
        .on_conflict_do_nothing(index_elements=[Notification.user_id, Notification.dedupe_key])
        .returning(Notification.id)
    )
    created = inserted.first()
    if created is None:
        return False
    # Push is decided when the job runs (preferences, quiet hours, live devices; BL-3.06).
    await platform.enqueue(
        session,
        queue="default",
        kind=PUSH_JOB,
        payload={"notification_id": str(created[0])},
        dedupe_key=f"push:{created[0]}",
    )
    return True


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


async def notify_from_event(
    session: AsyncSession, event_type: str, event_id: str, data: Mapping[str, Any]
) -> bool:
    """Map one domain event to (at most) one notification."""
    if event_type in ("follow.requested", "follow.created"):
        follower, followee = _uuid(data.get("follower_id")), _uuid(data.get("followee_id"))
        if follower is None or followee is None:
            return False
        kind = "follow_request" if event_type == "follow.requested" else "new_follower"
        return await notify(
            session,
            user_id=followee,
            kind=kind,
            actor_id=follower,
            entity_type="user",
            entity_id=follower,
            dedupe_key=f"{kind}:{follower}",
        )
    if event_type in ("post.reacted", "post.commented"):
        post, owner = _uuid(data.get("post_id")), _uuid(data.get("post_author_id"))
        actor = _uuid(data.get("user_id") or data.get("author_id"))
        if post is None or owner is None or actor is None:
            return False
        if event_type == "post.reacted":
            return await notify(
                session,
                user_id=owner,
                kind="post_reaction",
                actor_id=actor,
                entity_type="post",
                entity_id=post,
                payload={"post_id": str(post), "reaction": data.get("reaction")},
                dedupe_key=f"post_reaction:{post}:{actor}",
            )
        return await notify(
            session,
            user_id=owner,
            kind="post_comment",
            actor_id=actor,
            entity_type="post",
            entity_id=post,
            payload={"post_id": str(post), "comment_id": data.get("comment_id")},
            dedupe_key=f"post_comment:{data.get('comment_id') or event_id}",
        )
    if event_type in ("connection.requested", "connection.accepted"):
        requester, recipient = _uuid(data.get("requester_id")), _uuid(data.get("recipient_id"))
        if requester is None or recipient is None:
            return False
        requested = event_type == "connection.requested"
        to_user, actor = (recipient, requester) if requested else (requester, recipient)
        kind = "connection_request" if requested else "connection_accepted"
        return await notify(
            session,
            user_id=to_user,
            kind=kind,
            actor_id=actor,
            entity_type="user",
            entity_id=actor,
            payload={"request_id": data.get("request_id")},
            dedupe_key=f"{kind}:{data.get('request_id') or event_id}",
        )
    if event_type == "message.sent":
        return await _new_message(session, data)
    if event_type == "conversation.read":
        user, conversation = _uuid(data.get("user_id")), _uuid(data.get("conversation_id"))
        if user is None or conversation is None:
            return False
        await session.execute(
            update(Notification)
            .where(
                Notification.user_id == user,
                Notification.type == "new_message",
                Notification.entity_id == conversation,
                Notification.read_at.is_(None),
            )
            .values(read_at=func.now())
        )
        return False
    if event_type == "moderation.action_applied":
        affected = _uuid(data.get("user_id"))
        target_type = str(data.get("target_type"))
        variant = moderation_variant(str(data.get("action")), target_type)
        if affected is None or variant is None:
            return False
        target = _uuid(data.get("target_id"))
        return await notify(
            session,
            user_id=affected,
            kind="moderation_notice",
            entity_type=target_type,
            entity_id=target,
            payload={
                "variant": variant,
                "action": data.get("action"),
                "target_type": target_type,
                "target_id": str(target) if target else None,
                **(
                    {"restriction_kind": data["restriction_kind"]}
                    if data.get("restriction_kind")
                    else {}
                ),
            },
            dedupe_key=f"moderation:{data.get('action_id') or event_id}",
        )
    return False


async def _new_message(session: AsyncSession, data: Mapping[str, Any]) -> bool:
    """One unread ``new_message`` per conversation and recipient: later messages don't stack
    until the conversation is read. The sender listed who to notify (mute and level, DM-009);
    no message body is stored."""
    conversation, message = _uuid(data.get("conversation_id")), _uuid(data.get("message_id"))
    sender = _uuid(data.get("sender_id"))
    if conversation is None or message is None or sender is None:
        return False
    created = False
    for raw in data.get("notify_user_ids") or []:
        recipient = _uuid(raw)
        if recipient is None:
            continue
        pending = await session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == recipient,
                Notification.type == "new_message",
                Notification.entity_id == conversation,
                Notification.read_at.is_(None),
            )
        )
        if pending:
            continue
        created |= await notify(
            session,
            user_id=recipient,
            kind="new_message",
            actor_id=sender,
            entity_type="conversation",
            entity_id=conversation,
            payload={"conversation_id": str(conversation), "seq": data.get("seq")},
            dedupe_key=f"new_message:{message}",
        )
    return created


EVENTS = (
    "message.sent",
    "conversation.read",
    "follow.requested",
    "follow.created",
    "post.reacted",
    "post.commented",
    "moderation.action_applied",
    "connection.requested",
    "connection.accepted",
)


def subscribe(router: platform.EventRouter) -> None:
    for event_type in EVENTS:
        router.subscribe(event_type, queue="default", kind=JOB_KIND)


def make_handlers(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    push_sender: PushSender | None = None,
    push_cipher: identity.PushTokenCipher | None = None,
) -> dict[str, platform.JobHandler]:
    async def handle(job: platform.Job) -> None:
        payload = job.payload
        async with sessionmaker() as session, session.begin():
            await notify_from_event(
                session,
                str(payload["event_type"]),
                str(payload["event_id"]),
                payload.get("data") or {},
            )

    handlers: dict[str, platform.JobHandler] = {JOB_KIND: handle}
    if push_cipher is not None:
        handlers[PUSH_JOB] = push.make_handler(sessionmaker, push_sender, push_cipher)
    return handlers


class NotificationService:
    def __init__(
        self, *, sessionmaker: async_sessionmaker[AsyncSession], cursors: CursorCodec
    ) -> None:
        self._sessionmaker = sessionmaker
        self._cursors = cursors

    @staticmethod
    async def _visible(session: AsyncSession, user_id: uuid.UUID) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = [Notification.user_id == user_id]
        hidden = await trust_safety.blocked_ids(session, user_id)
        if hidden:
            conditions.append(
                Notification.actor_id.is_(None) | Notification.actor_id.not_in(hidden)
            )
        return conditions

    async def list(
        self,
        user_id: uuid.UUID,
        *,
        unread_only: bool,
        cursor: str | None,
        limit: int,
        locale: str | None,
    ) -> NotificationPage:
        """Newest first, in ``locale`` (from Accept-Language) or else the user's UI locale."""
        scope = f"notifications.{user_id}.{int(unread_only)}"
        async with self._sessionmaker() as session:
            conditions = await self._visible(session, user_id)
            if unread_only:
                conditions.append(Notification.read_at.is_(None))
            if cursor:
                position = self._cursors.decode(cursor, scope=scope)
                conditions.append(Notification.id < uuid.UUID(str(position["id"])))
            rows = list(
                (
                    await session.scalars(
                        select(Notification)
                        .where(and_(*conditions))
                        .order_by(Notification.id.desc())
                        .limit(limit + 1)
                    )
                ).all()
            )
            has_more = len(rows) > limit
            rows = rows[:limit]
            actors = await profiles.authors(
                session, [r.actor_id for r in rows if r.actor_id is not None]
            )
            locale = locale or await profiles.ui_locale(session, user_id)
        data = []
        for row in rows:
            actor = actors.get(row.actor_id) if row.actor_id else None
            title, body = render(
                row.type, row.payload, actor=actor.display_name if actor else None, locale=locale
            )
            data.append(
                NotificationOut(
                    id=row.id,
                    type=row.type,
                    actor=profiles.user_summary(actor) if actor else None,
                    entity_type=row.entity_type,
                    entity_id=row.entity_id,
                    title=title,
                    body=body,
                    data={k: v for k, v in row.payload.items() if k != "variant"},
                    read_at=row.read_at,
                    created_at=row.created_at,
                )
            )
        next_cursor = (
            self._cursors.encode({"id": str(rows[-1].id)}, scope=scope)
            if has_more and rows
            else None
        )
        return NotificationPage(
            data=data, page=PageInfo(next_cursor=next_cursor, has_more=has_more)
        )

    async def unread_count(self, user_id: uuid.UUID) -> int:
        async with self._sessionmaker() as session:
            conditions = await self._visible(session, user_id)
            count = await session.scalar(
                select(func.count())
                .select_from(Notification)
                .where(and_(*conditions, Notification.read_at.is_(None)))
            )
        return int(count or 0)

    async def mark_read(self, user_id: uuid.UUID, ids: Sequence[uuid.UUID] | None) -> None:
        """Mark the given notifications (or all, when ``ids`` is None) as read. Unknown or other
        users' IDs are ignored, so the call is idempotent and reveals nothing."""
        condition = and_(Notification.user_id == user_id, Notification.read_at.is_(None))
        if ids is not None:
            condition = and_(condition, Notification.id.in_(set(ids)))
        async with self._sessionmaker() as session, session.begin():
            await session.execute(update(Notification).where(condition).values(read_at=func.now()))


async def purge_expired(session: AsyncSession) -> int:
    """Notifications are kept 90 days (docs/04 §14)."""
    return await platform.delete_batch(
        session, Notification, Notification.created_at < platform.ago(days=90)
    )
