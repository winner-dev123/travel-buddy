"""Direct conversations and messages (BL-3.03; DM-001..013, docs/06).

- One direct conversation exists per pair (``direct_key``). Opening one needs an accepted
  connection (``403 connection_required``); an inactive account or a block either way reads as
  ``404``. An existing conversation still opens, so its history stays readable.
- Sending re-checks authorization every time (membership, platform restriction, connection and
  blocks). It locks the conversation row, assigns ``last_seq + 1`` and inserts the message in the
  same transaction. A retry with the same ``client_message_id`` returns the stored message
  (``200`` + ``Idempotent-Replayed``) without a new row or seq.
- Edits (sender only, 15 minutes) and deletes (tombstones: body, attachments, reactions and pins
  removed) keep the message's seq; nothing but a new message consumes one (docs/06 §6).
- Receipts are monotonic watermarks clamped to ``last_seq``. Another member's read state is shown
  only when both share read receipts (DM-007); delivery state is always shared in direct chats.
- ``message.sent`` lists the members to notify (not muted, level allows it). Events never carry
  message bodies.
- Messages of deleted accounts keep their seq but show no content; the daily retention job turns
  them into tombstones (docs/04 §14).
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import and_, delete, exists, func, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.ids import uuid7
from app.core.pagination import CursorCodec, PageInfo
from app.core.security.principal import Principal
from app.modules.connections import service as connections
from app.modules.identity import service as identity
from app.modules.media import service as media
from app.modules.messaging.domain import (
    MAX_PINS,
    USER_CONTENT,
    ConversationKind,
    DirectFacts,
    MessageKind,
    ModerationState,
    SendRestriction,
    can_edit,
    canonical_emoji,
    direct_key,
    direct_restriction,
    history_floor,
    should_notify,
    snippet,
)
from app.modules.messaging.models import (
    Conversation,
    ConversationMember,
    ConversationPin,
    Message,
    MessageAttachment,
    MessageMention,
    MessageReaction,
    MessageReceipt,
)
from app.modules.messaging.schemas import (
    ConversationOut,
    ConversationPage,
    MessageList,
    MessageOut,
    MessagePreview,
    MuteConversationRequest,
    OpenDirectConversationRequest,
    ReactionSummary,
    ReceiptState,
    SendMessageRequest,
    SeqPageInfo,
    UpdateReceiptsRequest,
)
from app.modules.platform import service as platform
from app.modules.profiles import service as profiles
from app.modules.trust_safety import service as trust_safety

Row = tuple[Conversation, ConversationMember]

logger = logging.getLogger(__name__)

# Realtime delivery (docs/06), injected by the composition root: called after commit with the
# users to tell and an event ``{"type": <server frame type>, "data": {...}}``. ``message.new``
# and ``message.updated`` carry only IDs; each connection loads the message for its own user,
# re-checking access at delivery time.
Publish = Callable[[Sequence[uuid.UUID], Mapping[str, Any]], Awaitable[None]]


class GroupChatPolicy(Protocol):
    @property
    def restriction(self) -> str | None: ...

    @property
    def permissions(self) -> frozenset[str]: ...

    @property
    def title(self) -> str | None: ...


# A group member's send rights and chat permissions, from the groups module (same layer).
GroupPolicy = Callable[[AsyncSession, uuid.UUID, uuid.UUID, datetime], Awaitable[GroupChatPolicy]]


def _not_found(what: str = "Conversation") -> AppError:
    return AppError(ErrorCode.NOT_FOUND, f"{what} not found.")


def _invalid(field: str, message: str) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_FAILED,
        message,
        errors=[FieldError(field=field, code="invalid", message=message)],
    )


def _floor(member: ConversationMember) -> int:
    return history_floor(
        joined_at_seq=member.joined_at_seq, cleared_through_seq=member.cleared_through_seq
    )


def _hidden(message: Message) -> bool:
    """Tombstoned, removed by moderation, or written by an account that no longer exists."""
    return (
        message.deleted_at is not None
        or message.moderation_state != ModerationState.VISIBLE
        or (message.sender_id is None and message.kind in USER_CONTENT)
    )


def _preview(message: Message) -> MessagePreview:
    hidden = _hidden(message)
    return MessagePreview(
        id=message.id,
        seq=message.seq,
        sender_id=message.sender_id,
        kind=message.kind,  # type: ignore[arg-type]
        snippet=None if hidden else snippet(message.body),
        deleted=hidden,
        created_at=message.created_at,
    )


async def _db_now(session: AsyncSession) -> datetime:
    now: datetime = await session.scalar(select(func.now()))  # type: ignore[assignment]
    return now


def _member_of(user_id: uuid.UUID) -> ColumnElement[bool]:
    return and_(
        ConversationMember.conversation_id == Conversation.id,
        ConversationMember.user_id == user_id,
        ConversationMember.left_at.is_(None),
    )


async def _access(
    session: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID, *, lock: bool = False
) -> Row:
    """The conversation and the caller's membership; ``404`` for non-members."""
    query = (
        select(Conversation, ConversationMember)
        .join(ConversationMember, _member_of(user_id))
        .where(Conversation.id == conversation_id)
    )
    if lock:
        query = query.with_for_update(of=Conversation)
    row = (await session.execute(query)).first()
    if row is None:
        raise _not_found()
    return row[0], row[1]


async def _message_in(
    session: AsyncSession,
    conversation: Conversation,
    member: ConversationMember,
    message_id: uuid.UUID,
    *,
    lock: bool = False,
) -> Message:
    message = await session.get(Message, message_id, with_for_update=lock)
    if (
        message is None
        or message.conversation_id != conversation.id
        or message.seq <= _floor(member)
    ):
        raise _not_found("Message")
    return message


async def _peers(
    session: AsyncSession, conversation_ids: Sequence[uuid.UUID], user_id: uuid.UUID
) -> dict[uuid.UUID, uuid.UUID]:
    """The other member of each direct conversation."""
    if not conversation_ids:
        return {}
    rows = await session.execute(
        select(ConversationMember.conversation_id, ConversationMember.user_id).where(
            ConversationMember.conversation_id.in_(set(conversation_ids)),
            ConversationMember.user_id != user_id,
        )
    )
    return {row[0]: row[1] for row in rows.all()}


async def _restrictions(
    session: AsyncSession,
    user_id: uuid.UUID,
    conversations: Sequence[Conversation],
    peers: Mapping[uuid.UUID, uuid.UUID],
    group_policy: GroupPolicy | None = None,
) -> dict[uuid.UUID, SendRestriction | None]:
    direct = [c for c in conversations if c.kind == ConversationKind.DIRECT]
    result: dict[uuid.UUID, SendRestriction | None] = {c.id: None for c in conversations}
    groups = [c for c in conversations if c.kind == ConversationKind.GROUP and c.group_id]
    if groups and group_policy is not None:
        now = await _db_now(session)
        for conversation in groups:
            assert conversation.group_id is not None
            policy = await group_policy(session, conversation.group_id, user_id, now)
            result[conversation.id] = (
                SendRestriction(policy.restriction) if policy.restriction else None
            )
    if not direct:
        return result
    others = [peers[c.id] for c in direct if c.id in peers]
    blocked_by_me, blocked_me = await trust_safety.blocks_of(session, user_id)
    active = await identity.active_ids(session, others)
    connected = await connections.connected_ids(session, user_id, others)
    for conversation in direct:
        other = peers.get(conversation.id)
        if other is None:  # the other account was deleted
            result[conversation.id] = SendRestriction.CONNECTION_REQUIRED
            continue
        result[conversation.id] = direct_restriction(
            DirectFacts(
                counterpart_active=other in active,
                blocked_by_me=other in blocked_by_me,
                blocked_me=other in blocked_me,
                connected=other in connected,
            )
        )
    return result


async def _ensure_can_send(
    session: AsyncSession,
    user_id: uuid.UUID,
    conversation: Conversation,
    group_policy: GroupPolicy | None = None,
) -> None:
    peers = (
        await _peers(session, [conversation.id], user_id)
        if conversation.kind == ConversationKind.DIRECT
        else {}
    )
    restriction = (await _restrictions(session, user_id, [conversation], peers, group_policy))[
        conversation.id
    ]
    if restriction is SendRestriction.MEMBER_RESTRICTED:
        raise AppError(ErrorCode.MEMBER_RESTRICTED, "You can't post in this group right now.")
    if restriction is SendRestriction.CHAT_ADMINS_ONLY:
        raise AppError(ErrorCode.CHAT_ADMINS_ONLY, "Only admins can post in this group.")
    if restriction is SendRestriction.ARCHIVED:
        raise AppError(ErrorCode.FORBIDDEN, "This group is archived.")
    if restriction is SendRestriction.BLOCKED:
        raise AppError(
            ErrorCode.BLOCKED_RELATIONSHIP, "You blocked this person. Unblock them to message."
        )
    if restriction is not None:
        raise AppError(
            ErrorCode.CONNECTION_REQUIRED, "You can message people you're connected with."
        )


async def _receipts(
    session: AsyncSession, pairs: Sequence[tuple[uuid.UUID, uuid.UUID]]
) -> dict[tuple[uuid.UUID, uuid.UUID], MessageReceipt]:
    if not pairs:
        return {}
    rows = await session.scalars(
        select(MessageReceipt).where(
            tuple_(MessageReceipt.conversation_id, MessageReceipt.user_id).in_(set(pairs))
        )
    )
    return {(r.conversation_id, r.user_id): r for r in rows}


async def _advance_receipt(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    read: int,
    delivered: int,
) -> tuple[int, int, datetime]:
    """Move watermarks forward only (``GREATEST``); returns the stored values."""
    table = MessageReceipt.__table__
    values = insert(MessageReceipt).values(
        conversation_id=conversation_id,
        user_id=user_id,
        read_through_seq=read,
        delivered_through_seq=max(delivered, read),
    )
    statement = values.on_conflict_do_update(
        index_elements=[MessageReceipt.conversation_id, MessageReceipt.user_id],
        set_={
            "read_through_seq": func.greatest(
                table.c.read_through_seq, values.excluded.read_through_seq
            ),
            "delivered_through_seq": func.greatest(
                table.c.delivered_through_seq, values.excluded.delivered_through_seq
            ),
            "updated_at": func.now(),
        },
    ).returning(
        MessageReceipt.read_through_seq,
        MessageReceipt.delivered_through_seq,
        MessageReceipt.updated_at,
    )
    row = (await session.execute(statement)).one()
    return int(row[0]), int(row[1]), row[2]


async def _conversations_out(
    session: AsyncSession,
    user_id: uuid.UUID,
    rows: Sequence[Row],
    group_policy: GroupPolicy | None = None,
) -> list[ConversationOut]:
    if not rows:
        return []
    conversations = [c for c, _ in rows]
    peers = await _peers(
        session, [c.id for c in conversations if c.kind == ConversationKind.DIRECT], user_id
    )
    users = await profiles.authors(session, list(set(peers.values())))
    restrictions = await _restrictions(session, user_id, conversations, peers, group_policy)
    titles: dict[uuid.UUID, str | None] = {}
    if group_policy is not None:
        now = await _db_now(session)
        for c in conversations:
            if c.kind == ConversationKind.GROUP and c.group_id:
                titles[c.id] = (await group_policy(session, c.group_id, user_id, now)).title
    receipts = await _receipts(
        session,
        [(c.id, user_id) for c in conversations] + [(c, u) for c, u in peers.items()],
    )
    sharing = await profiles.read_receipts_enabled(session, [user_id, *set(peers.values())])

    visible_last = [(c.id, c.last_seq) for c, m in rows if c.last_seq > _floor(m)]
    last: dict[uuid.UUID, Message] = {}
    if visible_last:
        found = await session.scalars(
            select(Message).where(tuple_(Message.conversation_id, Message.seq).in_(visible_last))
        )
        last = {m.conversation_id: m for m in found}

    unread: dict[uuid.UUID, int] = {}
    bounds = []
    for conversation, member in rows:
        mine = receipts.get((conversation.id, user_id))
        start = max(_floor(member), mine.read_through_seq if mine else 0)
        if conversation.last_seq > start:
            bounds.append(and_(Message.conversation_id == conversation.id, Message.seq > start))
    if bounds:
        counted = await session.execute(
            select(Message.conversation_id, func.count())
            .where(
                or_(*bounds),
                Message.deleted_at.is_(None),
                or_(Message.sender_id.is_(None), Message.sender_id != user_id),
            )
            .group_by(Message.conversation_id)
        )
        unread = {conversation: int(count) for conversation, count in counted.all()}

    out = []
    for conversation, member in rows:
        mine = receipts.get((conversation.id, user_id))
        peer = peers.get(conversation.id)
        theirs = receipts.get((conversation.id, peer)) if peer else None
        restriction = restrictions[conversation.id]
        direct = conversation.kind == ConversationKind.DIRECT
        out.append(
            ConversationOut(
                id=conversation.id,
                kind=conversation.kind,  # type: ignore[arg-type]
                title=titles.get(conversation.id),
                avatar=None,
                group_id=conversation.group_id,
                challenge_team_id=conversation.challenge_team_id,
                counterpart=profiles.user_summary(users[peer]) if peer in users else None,
                last_message=_preview(last[conversation.id]) if conversation.id in last else None,
                last_seq=conversation.last_seq,
                unread_count=unread.get(conversation.id, 0),
                read_through_seq=mine.read_through_seq if mine else 0,
                delivered_through_seq=mine.delivered_through_seq if mine else 0,
                peer_read_through_seq=(
                    (theirs.read_through_seq if theirs else 0)
                    if direct and peer and sharing.get(user_id) and sharing.get(peer)
                    else None
                ),
                peer_delivered_through_seq=(
                    (theirs.delivered_through_seq if theirs else 0) if direct and peer else None
                ),
                muted_until=member.muted_until,
                notification_level=member.notification_level,  # type: ignore[arg-type]
                can_send=restriction is None,
                send_restriction=restriction.value if restriction else None,
                created_at=conversation.created_at,
                last_message_at=conversation.last_message_at,
            )
        )
    return out


async def _messages_out(
    session: AsyncSession,
    user_id: uuid.UUID,
    member: ConversationMember,
    rows: Sequence[Message],
    sign: media.Signer | None = None,
) -> list[MessageOut]:
    """Messages as ``user_id`` sees them. Callers have checked membership, so private
    attachments get short-lived signed URLs (BL-3.05)."""
    if not rows:
        return []
    ids = [m.id for m in rows]
    shown = [m.id for m in rows if not _hidden(m)]
    senders = await profiles.authors(session, list({m.sender_id for m in rows if m.sender_id}))

    attachments: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    mentions: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    reactions: dict[uuid.UUID, list[ReactionSummary]] = defaultdict(list)
    if shown:
        for message_id, media_id in await session.execute(
            select(MessageAttachment.message_id, MessageAttachment.media_asset_id)
            .where(MessageAttachment.message_id.in_(shown))
            .order_by(MessageAttachment.message_id, MessageAttachment.sort_order)
        ):
            attachments[message_id].append(media_id)
        for message_id, mentioned in await session.execute(
            select(MessageMention.message_id, MessageMention.user_id).where(
                MessageMention.message_id.in_(shown)
            )
        ):
            mentions[message_id].append(mentioned)
        for message_id, emoji, count, mine in await session.execute(
            select(
                MessageReaction.message_id,
                MessageReaction.emoji,
                func.count(),
                func.bool_or(MessageReaction.user_id == user_id),
            )
            .where(MessageReaction.message_id.in_(shown))
            .group_by(MessageReaction.message_id, MessageReaction.emoji)
            .order_by(MessageReaction.message_id, func.min(MessageReaction.created_at))
        ):
            reactions[message_id].append(
                ReactionSummary(emoji=emoji, count=int(count), reacted_by_me=bool(mine))
            )
    refs = await media.refs(
        session, [i for media_ids in attachments.values() for i in media_ids], sign=sign
    )
    pinned = set(
        await session.scalars(
            select(ConversationPin.message_id).where(ConversationPin.message_id.in_(ids))
        )
    )
    threads = {
        root: int(count)
        for root, count in await session.execute(
            select(Message.thread_root_id, func.count())
            .where(Message.thread_root_id.in_(ids), Message.deleted_at.is_(None))
            .group_by(Message.thread_root_id)
        )
    }
    reply_ids = {m.reply_to_message_id for m in rows if m.reply_to_message_id}
    replies: dict[uuid.UUID, Message] = {}
    if reply_ids:
        replies = {
            m.id: m
            for m in await session.scalars(
                select(Message).where(Message.id.in_(reply_ids), Message.seq > _floor(member))
            )
        }

    out = []
    for m in rows:
        hidden = _hidden(m)
        reply = replies.get(m.reply_to_message_id) if m.reply_to_message_id else None
        out.append(
            MessageOut(
                id=m.id,
                conversation_id=m.conversation_id,
                seq=m.seq,
                client_message_id=m.client_message_id if m.sender_id == user_id else None,
                sender=profiles.user_summary(senders[m.sender_id])
                if m.sender_id in senders
                else None,
                kind=m.kind,  # type: ignore[arg-type]
                body=None if hidden else m.body,
                attachments=[refs[i] for i in attachments.get(m.id, []) if i in refs],
                reply_to=_preview(reply) if reply else None,
                thread_root_id=m.thread_root_id,
                thread_reply_count=threads.get(m.id, 0),
                mentions=mentions.get(m.id, []),
                reactions=reactions.get(m.id, []),
                pinned=m.id in pinned,
                moderation_state=m.moderation_state,  # type: ignore[arg-type]
                edited_at=m.edited_at,
                deleted_at=m.deleted_at,
                created_at=m.created_at,
            )
        )
    return out


async def _tombstone(session: AsyncSession, message: Message, *, by: uuid.UUID) -> None:
    """Delete for everyone (DM-010): erase body and attachments; drop reactions, mentions, pins."""
    media_ids = list(
        await session.scalars(
            select(MessageAttachment.media_asset_id).where(
                MessageAttachment.message_id == message.id
            )
        )
    )
    await media.erase_assets(session, media_ids)
    for model in (MessageAttachment, MessageReaction, MessageMention):
        await session.execute(delete(model).where(model.message_id == message.id))
    await session.execute(delete(ConversationPin).where(ConversationPin.message_id == message.id))
    message.body = None
    message.deleted_at = await _db_now(session)
    message.deleted_by = by


async def _active_members(session: AsyncSession, conversation_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        await session.scalars(
            select(ConversationMember.user_id).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.left_at.is_(None),
            )
        )
    )


def _message_event(
    kind: str, conversation_id: uuid.UUID, message_id: uuid.UUID, change: str | None = None
) -> dict[str, Any]:
    data: dict[str, Any] = {"conversation_id": str(conversation_id), "message_id": str(message_id)}
    if change is not None:
        data["change"] = change
    return {"type": kind, "data": data}


class MessagingService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        cursors: CursorCodec,
        publish: Publish | None = None,
        sign: media.Signer | None = None,
        group_policy: GroupPolicy | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._cursors = cursors
        self._publish = publish
        self._sign = sign
        self._group_policy = group_policy

    async def _permissions(
        self, session: AsyncSession, conversation: Conversation, user_id: uuid.UUID
    ) -> frozenset[str]:
        if conversation.kind != ConversationKind.GROUP or not conversation.group_id:
            return frozenset()
        if self._group_policy is None:
            return frozenset()
        policy = await self._group_policy(
            session, conversation.group_id, user_id, await _db_now(session)
        )
        return policy.permissions

    async def _emit(self, users: Sequence[uuid.UUID], event: Mapping[str, Any]) -> None:
        """Best effort: the database is the record, and clients catch up by seq (docs/06 §1)."""
        if self._publish is None or not users:
            return
        try:
            await self._publish(users, event)
        except Exception:  # pragma: no cover - transport failures never fail the request
            logger.warning("realtime_publish_failed", extra={"type": event.get("type")})

    # ───────────────────────────── conversations ─────────────────────────────

    async def list_conversations(
        self, user_id: uuid.UUID, *, kind: str | None, cursor: str | None, limit: int
    ) -> ConversationPage:
        scope = f"conversations.{user_id}.{kind or 'all'}"
        activity = func.coalesce(Conversation.last_message_at, Conversation.created_at)
        query = (
            select(Conversation, ConversationMember, activity)
            .join(ConversationMember, _member_of(user_id))
            # Empty direct conversations stay out of the list until someone writes.
            .where(or_(Conversation.kind != ConversationKind.DIRECT, Conversation.last_seq > 0))
        )
        if kind:
            query = query.where(Conversation.kind == kind)
        if cursor:
            position = self._cursors.decode(cursor, scope=scope)
            at = datetime.fromisoformat(str(position["at"]))
            after = uuid.UUID(str(position["id"]))
            query = query.where(or_(activity < at, and_(activity == at, Conversation.id < after)))
        async with self._sessionmaker() as session:
            found = (
                await session.execute(
                    query.order_by(activity.desc(), Conversation.id.desc()).limit(limit + 1)
                )
            ).all()
            has_more = len(found) > limit
            found = found[:limit]
            data = await _conversations_out(
                session, user_id, [(c, m) for c, m, _ in found], self._group_policy
            )
        next_cursor = (
            self._cursors.encode(
                {"at": found[-1][2].isoformat(), "id": str(found[-1][0].id)}, scope=scope
            )
            if has_more and found
            else None
        )
        return ConversationPage(
            data=data, page=PageInfo(next_cursor=next_cursor, has_more=has_more)
        )

    async def open_direct(
        self, principal: Principal, request: OpenDirectConversationRequest
    ) -> tuple[ConversationOut, bool]:
        me, them = principal.user_id, request.user_id
        if me == them:
            raise _invalid("/user_id", "You can't message yourself.")
        key = direct_key(me, them)
        async with self._sessionmaker() as session, session.begin():
            if not await identity.is_active(session, them) or await trust_safety.is_blocked(
                session, me, them
            ):
                raise _not_found("Traveller")
            conversation = await session.scalar(
                select(Conversation).where(Conversation.direct_key == key)
            )
            created = False
            if conversation is None:
                if them not in await connections.connected_ids(session, me, [them]):
                    raise AppError(
                        ErrorCode.CONNECTION_REQUIRED,
                        "You can message people you're connected with.",
                    )
                new_id = (
                    await session.execute(
                        insert(Conversation)
                        .values(id=uuid7(), kind=ConversationKind.DIRECT, direct_key=key)
                        .on_conflict_do_nothing(index_elements=[Conversation.direct_key])
                        .returning(Conversation.id)
                    )
                ).scalar_one_or_none()
                if new_id is not None:
                    created = True
                    await session.execute(
                        insert(ConversationMember)
                        .values([{"conversation_id": new_id, "user_id": u} for u in (me, them)])
                        .on_conflict_do_nothing()
                    )
                conversation = await session.scalar(
                    select(Conversation).where(Conversation.direct_key == key)
                )
                assert conversation is not None
            member = await session.get(ConversationMember, (conversation.id, me))
            if member is None:
                raise _not_found()
            [out] = await _conversations_out(
                session, me, [(conversation, member)], self._group_policy
            )
        if created:
            await self._emit(
                [me, them],
                {
                    "type": "conversation.updated",
                    "data": {"conversation_id": str(out.id), "created": True},
                },
            )
        return out, created

    async def get_conversation(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> ConversationOut:
        async with self._sessionmaker() as session:
            row = await _access(session, conversation_id, user_id)
            [out] = await _conversations_out(session, user_id, [row], self._group_policy)
        return out

    async def mute(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, request: MuteConversationRequest
    ) -> ConversationOut:
        async with self._sessionmaker() as session, session.begin():
            conversation, member = await _access(session, conversation_id, user_id)
            member.muted_until = request.muted_until
            if request.notification_level is not None:
                member.notification_level = request.notification_level
            await session.flush()
            [out] = await _conversations_out(
                session, user_id, [(conversation, member)], self._group_policy
            )
        await self._emit(
            [user_id],
            {
                "type": "conversation.updated",
                "data": {
                    "conversation_id": str(out.id),
                    "muted_until": out.muted_until.isoformat() if out.muted_until else None,
                    "notification_level": out.notification_level,
                },
            },
        )
        return out

    async def clear(self, user_id: uuid.UUID, conversation_id: uuid.UUID, through_seq: int) -> None:
        """Hide history up to ``through_seq`` for the caller only (DM-009)."""
        async with self._sessionmaker() as session, session.begin():
            conversation, member = await _access(session, conversation_id, user_id)
            through = min(through_seq, conversation.last_seq)
            member.cleared_through_seq = max(member.cleared_through_seq, through)
            await _advance_receipt(
                session, conversation.id, user_id, read=through, delivered=through
            )

    async def update_receipts(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, request: UpdateReceiptsRequest
    ) -> ReceiptState:
        async with self._sessionmaker() as session, session.begin():
            conversation, _ = await _access(session, conversation_id, user_id)
            top = conversation.last_seq
            read = min(request.read_through_seq or 0, top)
            delivered = min(request.delivered_through_seq or 0, top)
            previous = (
                await session.execute(
                    select(
                        MessageReceipt.read_through_seq, MessageReceipt.delivered_through_seq
                    ).where(
                        MessageReceipt.conversation_id == conversation.id,
                        MessageReceipt.user_id == user_id,
                    )
                )
            ).first()
            before, before_delivered = (previous[0], previous[1]) if previous else (0, 0)
            read, delivered, updated_at = await _advance_receipt(
                session, conversation.id, user_id, read=read, delivered=delivered
            )
            others = [u for u in await _active_members(session, conversation.id) if u != user_id]
            sharing = await profiles.read_receipts_enabled(session, [user_id, *others])
            direct = conversation.kind == ConversationKind.DIRECT
            deliveries: list[tuple[uuid.UUID, dict[str, Any]]] = []
            for other in others:
                data: dict[str, Any] = {}
                if read > before and sharing.get(user_id) and sharing.get(other):
                    data["read_through_seq"] = read
                if direct and delivered > before_delivered:
                    data["delivered_through_seq"] = delivered
                if data:
                    deliveries.append((other, data))
            if read > (before or 0):
                platform.record_event(
                    session,
                    aggregate_type="conversation",
                    aggregate_id=conversation.id,
                    event_type="conversation.read",
                    payload={
                        "conversation_id": str(conversation.id),
                        "user_id": str(user_id),
                        "read_through_seq": read,
                    },
                )
        for other, data in deliveries:
            await self._emit(
                [other],
                {
                    "type": "receipt.updated",
                    "data": {
                        "conversation_id": str(conversation_id),
                        "user_id": str(user_id),
                        **data,
                    },
                },
            )
        return ReceiptState(
            conversation_id=conversation_id,
            read_through_seq=read,
            delivered_through_seq=delivered,
            updated_at=updated_at,
        )

    # ─────────────────────────────── messages ───────────────────────────────

    async def list_messages(
        self,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        *,
        before_seq: int | None,
        after_seq: int | None,
        limit: int,
    ) -> MessageList:
        if before_seq is not None and after_seq is not None:
            raise _invalid("/after_seq", "Send before_seq or after_seq, not both.")
        async with self._sessionmaker() as session:
            conversation, member = await _access(session, conversation_id, user_id)
            query = select(Message).where(
                Message.conversation_id == conversation.id, Message.seq > _floor(member)
            )
            if after_seq is not None:
                found = list(
                    await session.scalars(
                        query.where(Message.seq > after_seq).order_by(Message.seq).limit(limit + 1)
                    )
                )
                has_more = len(found) > limit
                rows = found[:limit]
            else:
                if before_seq is not None:
                    query = query.where(Message.seq < before_seq)
                found = list(
                    await session.scalars(query.order_by(Message.seq.desc()).limit(limit + 1))
                )
                has_more = len(found) > limit
                rows = list(reversed(found[:limit]))
            data = await _messages_out(session, user_id, member, rows, self._sign)
        return MessageList(
            data=data,
            page=SeqPageInfo(
                has_more=has_more,
                oldest_seq=rows[0].seq if rows else None,
                newest_seq=rows[-1].seq if rows else None,
            ),
        )

    async def send(
        self, principal: Principal, conversation_id: uuid.UUID, request: SendMessageRequest
    ) -> tuple[MessageOut, bool]:
        return await self._send(principal, conversation_id, request)

    async def announce(
        self,
        principal: Principal,
        conversation_id: uuid.UUID,
        client_message_id: uuid.UUID,
        body: str,
        pin: bool,
    ) -> dict[str, Any]:
        """A group announcement (GCHAT-003); the group checked ``announcements.post``."""
        out, _ = await self._send(
            principal,
            conversation_id,
            SendMessageRequest(client_message_id=client_message_id, body=body),
            kind=MessageKind.ANNOUNCEMENT,
        )
        if pin:
            await self.pin(principal.user_id, conversation_id, out.id, on=True)
            out = await self.get_message(principal.user_id, conversation_id, out.id)
        return out.model_dump(mode="json")

    async def _send(
        self,
        principal: Principal,
        conversation_id: uuid.UUID,
        request: SendMessageRequest,
        *,
        kind: str | None = None,
    ) -> tuple[MessageOut, bool]:
        me = principal.user_id
        async with self._sessionmaker() as session, session.begin():
            # The row lock serializes sends per conversation: seq order and duplicate checks.
            conversation, member = await _access(session, conversation_id, me, lock=True)
            existing = await session.scalar(
                select(Message).where(
                    Message.conversation_id == conversation.id,
                    Message.sender_id == me,
                    Message.client_message_id == request.client_message_id,
                )
            )
            if existing is not None:
                [out] = await _messages_out(session, me, member, [existing], self._sign)
                return out, True
            await trust_safety.ensure_not_restricted(
                session,
                me,
                "messaging_limited",
                message="Messaging is limited on your account right now.",
            )
            if kind != MessageKind.ANNOUNCEMENT:  # admins may announce in admins-only chats
                await _ensure_can_send(session, me, conversation, self._group_policy)
            floor = _floor(member)
            if request.reply_to_message_id is not None:
                target = await session.get(Message, request.reply_to_message_id)
                if (
                    target is None
                    or target.conversation_id != conversation.id
                    or target.seq <= floor
                ):
                    raise _invalid("/reply_to_message_id", "That message isn't in this chat.")
            if request.thread_root_id is not None:
                root = await session.get(Message, request.thread_root_id)
                if (
                    conversation.kind == ConversationKind.DIRECT
                    or root is None
                    or root.conversation_id != conversation.id
                    or root.thread_root_id is not None
                ):
                    raise _invalid("/thread_root_id", "Threads are available in group chats.")
            attachment_ids = request.attachment_media_ids or []
            if attachment_ids:
                usable = await media.usable_ids(session, me, attachment_ids, "message")
                if usable != set(attachment_ids):
                    raise _invalid("/attachment_media_ids", "Upload each image for messages first.")
            mentions: list[uuid.UUID] = []
            if request.mentions:
                members = set(
                    await session.scalars(
                        select(ConversationMember.user_id).where(
                            ConversationMember.conversation_id == conversation.id,
                            ConversationMember.left_at.is_(None),
                            ConversationMember.user_id.in_(request.mentions),
                        )
                    )
                )
                mentions = [u for u in request.mentions if u in members and u != me]

            conversation.last_seq += 1
            message = Message(
                conversation_id=conversation.id,
                seq=conversation.last_seq,
                sender_id=me,
                client_message_id=request.client_message_id,
                kind=kind or request.kind,
                body=request.body,
                reply_to_message_id=request.reply_to_message_id,
                thread_root_id=request.thread_root_id,
            )
            session.add(message)
            await session.flush()
            conversation.last_message_at = message.created_at
            session.add_all(
                [
                    MessageAttachment(message_id=message.id, media_asset_id=m, sort_order=i)
                    for i, m in enumerate(attachment_ids)
                ]
                + [MessageMention(message_id=message.id, user_id=u) for u in mentions]
            )
            await session.flush()
            await _advance_receipt(
                session, conversation.id, me, read=message.seq, delivered=message.seq
            )
            now = await _db_now(session)
            others = await session.execute(
                select(
                    ConversationMember.user_id,
                    ConversationMember.muted_until,
                    ConversationMember.notification_level,
                ).where(
                    ConversationMember.conversation_id == conversation.id,
                    ConversationMember.left_at.is_(None),
                    ConversationMember.user_id != me,
                )
            )
            member_rows = others.all()
            recipients = [me, *(user for user, _, _ in member_rows)]
            notify = [
                str(user)
                for user, muted_until, level in member_rows
                if should_notify(
                    level=level, muted_until=muted_until, now=now, mentioned=user in mentions
                )
            ]
            platform.record_event(
                session,
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                event_type="message.sent",
                payload={
                    "conversation_id": str(conversation.id),
                    "conversation_kind": conversation.kind,
                    "message_id": str(message.id),
                    "seq": message.seq,
                    "sender_id": str(me),
                    "kind": message.kind,
                    "notify_user_ids": notify,
                },
            )
            [out] = await _messages_out(session, me, member, [message], self._sign)
        await self._emit(recipients, _message_event("message.new", out.conversation_id, out.id))
        return out, False

    async def edit(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, message_id: uuid.UUID, body: str
    ) -> MessageOut:
        if not body.strip():
            raise _invalid("/body", "Write something.")
        async with self._sessionmaker() as session, session.begin():
            conversation, member = await _access(session, conversation_id, user_id)
            message = await _message_in(session, conversation, member, message_id, lock=True)
            if message.sender_id != user_id or message.kind not in USER_CONTENT:
                raise AppError(ErrorCode.FORBIDDEN, "You can edit only your own messages.")
            if _hidden(message):
                raise _not_found("Message")
            now = await _db_now(session)
            if not can_edit(created_at=message.created_at, now=now):
                raise AppError(
                    ErrorCode.MESSAGE_EDIT_WINDOW_EXPIRED,
                    "Messages can be edited for 15 minutes after sending.",
                )
            await _ensure_can_send(session, user_id, conversation, self._group_policy)
            message.body = body
            message.edited_at = now
            platform.record_event(
                session,
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                event_type="message.edited",
                payload={
                    "conversation_id": str(conversation.id),
                    "message_id": str(message.id),
                    "seq": message.seq,
                },
            )
            await session.flush()
            [out] = await _messages_out(session, user_id, member, [message], self._sign)
            recipients = await _active_members(session, conversation.id)
        await self._emit(
            recipients, _message_event("message.updated", out.conversation_id, out.id, "edited")
        )
        return out

    async def delete(
        self,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID,
        *,
        reason_code: str | None = None,
    ) -> None:
        """Delete for everyone (sender), or remove as a group moderator with ``messages.remove``
        (recorded as a moderation action; GCHAT-004). Idempotent."""
        async with self._sessionmaker() as session, session.begin():
            conversation, member = await _access(session, conversation_id, user_id)
            message = await _message_in(session, conversation, member, message_id, lock=True)
            if message.deleted_at is not None:
                return
            by_moderator = message.sender_id != user_id
            if by_moderator:
                if "messages.remove" not in await self._permissions(session, conversation, user_id):
                    raise AppError(ErrorCode.FORBIDDEN, "You can delete only your own messages.")
                if not reason_code:
                    raise _invalid("/reason_code", "Say why you're removing this message.")
                message.moderation_state = ModerationState.REMOVED_BY_MODERATOR
                await trust_safety.record_action(
                    session,
                    target_type="message",
                    target_id=message.id,
                    action="remove_content",
                    reason_code=reason_code,
                    notes=None,
                    actor_id=user_id,
                    report_id=None,
                    expires_at=None,
                    group_id=conversation.group_id,
                )
            await _tombstone(session, message, by=user_id)
            platform.record_event(
                session,
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                event_type="message.deleted",
                payload={
                    "conversation_id": str(conversation.id),
                    "message_id": str(message.id),
                    "seq": message.seq,
                    "by_moderator": by_moderator,
                },
            )
            recipients = await _active_members(session, conversation.id)
            tombstone = {
                "conversation_id": str(conversation.id),
                "message_id": str(message.id),
                "seq": message.seq,
                "deleted_at": message.deleted_at.isoformat() if message.deleted_at else None,
                "by_moderator": by_moderator,
            }
        await self._emit(recipients, {"type": "message.deleted", "data": tombstone})

    async def react(
        self,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID,
        emoji: str,
        *,
        add: bool,
    ) -> None:
        """Add or remove a reaction (both idempotent)."""
        stored = canonical_emoji(emoji)
        if stored is None and add:
            raise _invalid("/emoji", "That reaction isn't available.")
        async with self._sessionmaker() as session, session.begin():
            conversation, member = await _access(session, conversation_id, user_id)
            message = await _message_in(session, conversation, member, message_id)
            if stored is None:
                return
            if not add:
                removed = await session.execute(
                    delete(MessageReaction).where(
                        MessageReaction.message_id == message.id,
                        MessageReaction.user_id == user_id,
                        MessageReaction.emoji == stored,
                    )
                )
                changed = bool(getattr(removed, "rowcount", 0))
            else:
                if _hidden(message):
                    raise _not_found("Message")
                await _ensure_can_send(session, user_id, conversation, self._group_policy)
                added = await session.execute(
                    insert(MessageReaction)
                    .values(message_id=message.id, user_id=user_id, emoji=stored)
                    .on_conflict_do_nothing()
                    .returning(MessageReaction.emoji)
                )
                changed = added.first() is not None
            if not changed:
                return
            recipients = await _active_members(session, conversation.id)
            platform.record_event(
                session,
                aggregate_type="conversation",
                aggregate_id=conversation.id,
                event_type="message.reacted",
                payload={
                    "conversation_id": str(conversation.id),
                    "message_id": str(message.id),
                    "user_id": str(user_id),
                },
            )
        await self._emit(
            recipients, _message_event("message.updated", conversation_id, message_id, "reactions")
        )

    async def thread(
        self,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message_id: uuid.UUID,
        *,
        after_seq: int | None,
        limit: int,
    ) -> MessageList:
        async with self._sessionmaker() as session:
            conversation, member = await _access(session, conversation_id, user_id)
            root = await _message_in(session, conversation, member, message_id)
            found = list(
                await session.scalars(
                    select(Message)
                    .where(
                        Message.thread_root_id == root.id,
                        Message.seq > max(after_seq or 0, _floor(member)),
                    )
                    .order_by(Message.seq)
                    .limit(limit + 1)
                )
            )
            rows = found[:limit]
            data = await _messages_out(session, user_id, member, rows, self._sign)
        return MessageList(
            data=data,
            page=SeqPageInfo(
                has_more=len(found) > limit,
                oldest_seq=rows[0].seq if rows else None,
                newest_seq=rows[-1].seq if rows else None,
            ),
        )

    # ──────────────────────────────── pins ────────────────────────────────

    async def pins(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> MessageList:
        async with self._sessionmaker() as session:
            conversation, member = await _access(session, conversation_id, user_id)
            rows = list(
                await session.scalars(
                    select(Message)
                    .join(ConversationPin, ConversationPin.message_id == Message.id)
                    .where(ConversationPin.conversation_id == conversation.id)
                    .order_by(ConversationPin.pinned_at.desc())
                    .limit(MAX_PINS)
                )
            )
            data = await _messages_out(session, user_id, member, rows, self._sign)
        seqs = [m.seq for m in rows]
        return MessageList(
            data=data,
            page=SeqPageInfo(
                has_more=False,
                oldest_seq=min(seqs) if seqs else None,
                newest_seq=max(seqs) if seqs else None,
            ),
        )

    async def pin(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, message_id: uuid.UUID, *, on: bool
    ) -> None:
        """Pin or unpin (idempotent). In direct chats either member may pin; at most 10."""
        async with self._sessionmaker() as session, session.begin():
            conversation, member = await _access(session, conversation_id, user_id, lock=True)
            message = await _message_in(session, conversation, member, message_id)
            if conversation.kind == ConversationKind.GROUP and "messages.pin" not in (
                await self._permissions(session, conversation, user_id)
            ):
                raise AppError(ErrorCode.FORBIDDEN, "Only moderators can pin in this group.")
            if not on:
                unpinned = await session.execute(
                    delete(ConversationPin).where(
                        ConversationPin.conversation_id == conversation.id,
                        ConversationPin.message_id == message.id,
                    )
                )
                if not getattr(unpinned, "rowcount", 0):
                    return
            else:
                if _hidden(message):
                    raise _not_found("Message")
                already = await session.get(ConversationPin, (conversation.id, message.id))
                if already is not None:
                    return
                count = await session.scalar(
                    select(func.count())
                    .select_from(ConversationPin)
                    .where(ConversationPin.conversation_id == conversation.id)
                )
                if (count or 0) >= MAX_PINS:
                    raise AppError(ErrorCode.CONFLICT, f"A chat can have up to {MAX_PINS} pins.")
                session.add(
                    ConversationPin(
                        conversation_id=conversation.id, message_id=message.id, pinned_by=user_id
                    )
                )
            recipients = await _active_members(session, conversation.id)
        await self._emit(
            recipients,
            _message_event(
                "message.updated", conversation_id, message_id, "pinned" if on else "unpinned"
            ),
        )

    # ─────────────────────────────── realtime ───────────────────────────────

    async def get_message(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, message_id: uuid.UUID
    ) -> MessageOut:
        """One message as ``user_id`` sees it (``404`` without access), for realtime frames."""
        async with self._sessionmaker() as session:
            conversation, member = await _access(session, conversation_id, user_id)
            message = await _message_in(session, conversation, member, message_id)
            [out] = await _messages_out(session, user_id, member, [message], self._sign)
        return out

    async def sync(
        self,
        user_id: uuid.UUID,
        held: Sequence[tuple[uuid.UUID, int]],
        *,
        list_synced_at: datetime | None,
    ) -> list[tuple[uuid.UUID, int, int]]:
        """Conversations the client is behind on: ``(id, from_seq, server_last_seq)``. Unknown
        or inaccessible IDs are skipped; with ``list_synced_at``, conversations active since
        then that the client doesn't hold are reported from seq 0."""
        positions = dict(held)
        async with self._sessionmaker() as session:
            query = select(Conversation, ConversationMember).join(
                ConversationMember, _member_of(user_id)
            )
            conditions: list[ColumnElement[bool]] = []
            if positions:
                conditions.append(Conversation.id.in_(positions))
            if list_synced_at is not None:
                conditions.append(Conversation.last_message_at > list_synced_at)
            if not conditions:
                return []
            rows = (await session.execute(query.where(or_(*conditions)))).all()
        behind = []
        for conversation, member in rows:
            start = max(positions.get(conversation.id, 0), _floor(member))
            if conversation.last_seq > start:
                behind.append((conversation.id, start, conversation.last_seq))
        return behind

    async def typing_recipients(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> list[uuid.UUID]:
        """Who sees the caller typing: other members, never across a block, and nobody when
        the caller can't send (docs/06 §11)."""
        async with self._sessionmaker() as session:
            conversation, _ = await _access(session, conversation_id, user_id)
            try:
                await _ensure_can_send(session, user_id, conversation, self._group_policy)
            except AppError:
                return []
            blocked_by_me, blocked_me = await trust_safety.blocks_of(session, user_id)
            hidden = blocked_by_me | blocked_me
            return [
                u
                for u in await _active_members(session, conversation.id)
                if u != user_id and u not in hidden
            ]

    async def active_conversation_ids(self, user_id: uuid.UUID) -> set[uuid.UUID]:
        async with self._sessionmaker() as session:
            rows = await session.scalars(
                select(ConversationMember.conversation_id).where(
                    ConversationMember.user_id == user_id, ConversationMember.left_at.is_(None)
                )
            )
            return set(rows)


# ─────────────────────────────── for other modules ───────────────────────────────


async def message_evidence(
    session: AsyncSession, message_id: uuid.UUID, reporter_id: uuid.UUID
) -> tuple[uuid.UUID | None, dict[str, Any]] | None:
    """Report evidence (DM-012): only a member who can see the message may report it."""
    message = await session.get(Message, message_id)
    if message is None or message.sender_id == reporter_id:
        return None
    member = await session.get(ConversationMember, (message.conversation_id, reporter_id))
    if member is None or member.left_at is not None or message.seq <= _floor(member):
        return None
    attachments = list(
        await session.scalars(
            select(MessageAttachment.media_asset_id)
            .where(MessageAttachment.message_id == message.id)
            .order_by(MessageAttachment.sort_order)
        )
    )
    return message.sender_id, {
        "conversation_id": str(message.conversation_id),
        "seq": message.seq,
        "kind": message.kind,
        "body": None if _hidden(message) else message.body,
        "attachment_ids": [str(a) for a in attachments],
        "created_at": message.created_at.isoformat(),
        "edited_at": message.edited_at.isoformat() if message.edited_at else None,
    }


async def moderate_message(
    session: AsyncSession, message_id: uuid.UUID, *, remove: bool
) -> uuid.UUID | None:
    """Staff remove or restore a message (ADM-002); returns the sender."""
    message = await session.get(Message, message_id, with_for_update=True)
    if message is None:
        raise _not_found("Message")
    message.moderation_state = (
        ModerationState.REMOVED_BY_ADMIN if remove else ModerationState.VISIBLE
    )
    platform.record_event(
        session,
        aggregate_type="conversation",
        aggregate_id=message.conversation_id,
        event_type="message.moderated",
        payload={
            "conversation_id": str(message.conversation_id),
            "message_id": str(message.id),
            "seq": message.seq,
            "state": message.moderation_state,
        },
    )
    return message.sender_id


async def purge_expired(session: AsyncSession) -> int:
    """Tombstone messages of deleted accounts; drop direct chats nobody is left in."""
    orphaned = (
        select(Message.id)
        .where(
            Message.sender_id.is_(None),
            Message.deleted_at.is_(None),
            Message.kind.in_([k.value for k in USER_CONTENT]),
        )
        .limit(5000)
    )
    erased = await session.execute(
        update(Message)
        .where(Message.id.in_(orphaned))
        .values(body=None, deleted_at=func.now())
        .execution_options(synchronize_session=False)
    )
    empty = await platform.delete_batch(
        session,
        Conversation,
        (Conversation.kind == ConversationKind.DIRECT)
        & ~exists().where(ConversationMember.conversation_id == Conversation.id),
    )
    return int(getattr(erased, "rowcount", 0) or 0) + empty


__all__ = ["MessageKind", "MessagingService", "message_evidence", "moderate_message"]


async def create_group_conversation(
    session: AsyncSession, group_id: uuid.UUID, owner_id: uuid.UUID
) -> uuid.UUID:
    """The group's one chat room (GCHAT-001), created with the group."""
    conversation = Conversation(kind=ConversationKind.GROUP, group_id=group_id)
    session.add(conversation)
    await session.flush()
    session.add(ConversationMember(conversation_id=conversation.id, user_id=owner_id))
    await session.flush()
    return conversation.id


async def create_team_conversation(
    session: AsyncSession, team_id: uuid.UUID, captain_id: uuid.UUID
) -> uuid.UUID:
    """A challenge team's thread (CHAL-004), created with the team. Members join and leave it
    through ``add_group_member`` / ``remove_group_member``."""
    conversation = Conversation(kind=ConversationKind.CHALLENGE_TEAM, challenge_team_id=team_id)
    session.add(conversation)
    await session.flush()
    session.add(ConversationMember(conversation_id=conversation.id, user_id=captain_id))
    await session.flush()
    return conversation.id


async def add_group_member(
    session: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID, *, from_join: bool
) -> None:
    """Join (or rejoin) a group or team chat; with ``from_join`` history starts at the join
    (GCHAT-006)."""
    conversation = await session.get(Conversation, conversation_id, with_for_update=True)
    if conversation is None:
        return
    floor = conversation.last_seq if from_join else 0
    member = await session.get(ConversationMember, (conversation_id, user_id))
    if member is None:
        session.add(
            ConversationMember(
                conversation_id=conversation_id, user_id=user_id, joined_at_seq=floor
            )
        )
    else:
        member.left_at = None
        member.joined_at_seq = floor
    await session.flush()


async def remove_group_member(
    session: AsyncSession, conversation_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Access ends at once: every read and send checks membership (GCHAT-007)."""
    await session.execute(
        update(ConversationMember)
        .where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id,
            ConversationMember.left_at.is_(None),
        )
        .values(left_at=func.now())
    )


async def export_user_data(
    session: AsyncSession, user_id: uuid.UUID
) -> dict[str, list[dict[str, object]]]:
    """Personal-data export (BL-6.03; AUTH-011): what this module holds about the user."""
    return {
        "messages_sent": await platform.export_rows(
            session, Message, Message.sender_id == user_id, exclude=("client_message_id",)
        ),
        "message_reactions": await platform.export_rows(
            session, MessageReaction, MessageReaction.user_id == user_id
        ),
        "conversations": await platform.export_rows(
            session, ConversationMember, ConversationMember.user_id == user_id
        ),
    }
