"""Messaging API shapes (contract ``Conversation``, ``Message``, ``MessageList`` and requests)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.pagination import PageInfo
from app.modules.media.schemas import MediaRef
from app.modules.profiles.schemas import UserSummary

Kind = Literal["direct", "group", "challenge_team"]
MessageKindName = Literal["text", "image", "system", "announcement", "gift"]
# DM-016: the gift catalog (mirrors ``domain.Gift``; the app ships the pictures).
GiftCode = Literal[
    "coffee", "postcard", "flowers", "ice_cream", "cake", "boarding_pass", "snow_globe", "coconut"
]
# DM-016: what plays when a gift is opened (mirrors ``domain.GiftEffect``).
GiftEffectName = Literal["petals", "splash", "confetti", "hearts"]
Level = Literal["all", "mentions", "none"]
Restriction = Literal[
    "connection_required", "blocked", "member_restricted", "chat_admins_only", "archived"
]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Response(BaseModel):
    model_config = ConfigDict(frozen=True)


class OpenDirectConversationRequest(_Request):
    kind: Literal["direct"]
    user_id: uuid.UUID


class SendMessageRequest(_Request):
    client_message_id: uuid.UUID
    kind: Literal["text", "image", "gift"] = "text"
    body: str | None = Field(default=None, min_length=1, max_length=4000)
    gift: GiftCode | None = None
    gift_effect: GiftEffectName | None = None
    attachment_media_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=10)
    reply_to_message_id: uuid.UUID | None = None
    thread_root_id: uuid.UUID | None = None
    mentions: list[uuid.UUID] | None = Field(default=None, max_length=20)

    @model_validator(mode="after")
    def _content(self) -> Self:
        if self.body is not None and not self.body.strip():
            raise ValueError("body must not be blank")
        if self.kind == "gift":
            if self.gift is None:
                raise ValueError("gift messages name a gift")
            if self.body is not None or self.attachment_media_ids:
                raise ValueError("a gift has no body or attachments")
            return self
        if self.gift is not None or self.gift_effect is not None:
            raise ValueError("gift and gift_effect are only for gift messages")
        if self.body is None and not self.attachment_media_ids:
            raise ValueError("a message needs a body or attachments")
        if self.kind == "image" and not self.attachment_media_ids:
            raise ValueError("image messages need attachment_media_ids")
        if self.mentions and len(set(self.mentions)) != len(self.mentions):
            raise ValueError("mentions must be unique")
        if self.attachment_media_ids and len(set(self.attachment_media_ids)) != len(
            self.attachment_media_ids
        ):
            raise ValueError("attachment_media_ids must be unique")
        return self


class EditMessageRequest(_Request):
    body: str = Field(min_length=1, max_length=4000)


class UpdateReceiptsRequest(_Request):
    read_through_seq: int | None = Field(default=None, ge=0)
    delivered_through_seq: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _one(self) -> Self:
        if self.read_through_seq is None and self.delivered_through_seq is None:
            raise ValueError("send read_through_seq or delivered_through_seq")
        return self


class MuteConversationRequest(_Request):
    muted_until: datetime | None
    notification_level: Level | None = None


class ClearConversationRequest(_Request):
    through_seq: int = Field(ge=0)


class MessagePreview(_Response):
    id: uuid.UUID
    seq: int
    sender_id: uuid.UUID | None
    kind: MessageKindName
    snippet: str | None
    deleted: bool
    created_at: datetime


class ConversationOut(_Response):
    id: uuid.UUID
    kind: Kind
    title: str | None
    avatar: MediaRef | None
    group_id: uuid.UUID | None
    challenge_team_id: uuid.UUID | None
    counterpart: UserSummary | None
    last_message: MessagePreview | None
    last_seq: int
    unread_count: int
    read_through_seq: int
    delivered_through_seq: int
    # The other member's watermarks (direct only). Read state only when both share receipts.
    peer_read_through_seq: int | None = None
    peer_delivered_through_seq: int | None = None
    muted_until: datetime | None
    notification_level: Level
    can_send: bool
    send_restriction: Restriction | None
    created_at: datetime
    last_message_at: datetime | None


class ConversationPage(_Response):
    data: list[ConversationOut]
    page: PageInfo


class ReactionSummary(_Response):
    emoji: str
    count: int
    reacted_by_me: bool


class GiftOut(_Response):
    code: GiftCode
    effect: GiftEffectName
    opened_at: datetime | None


class MessageOut(_Response):
    id: uuid.UUID
    conversation_id: uuid.UUID
    seq: int
    client_message_id: uuid.UUID | None = None
    sender: UserSummary | None
    kind: MessageKindName
    body: str | None
    gift: GiftOut | None = None
    attachments: list[MediaRef]
    reply_to: MessagePreview | None
    thread_root_id: uuid.UUID | None
    thread_reply_count: int
    mentions: list[uuid.UUID]
    reactions: list[ReactionSummary]
    pinned: bool
    moderation_state: Literal["visible", "removed_by_moderator", "removed_by_admin"]
    edited_at: datetime | None
    deleted_at: datetime | None
    created_at: datetime


class SeqPageInfo(_Response):
    has_more: bool
    oldest_seq: int | None
    newest_seq: int | None


class MessageList(_Response):
    data: list[MessageOut]
    page: SeqPageInfo


class ReceiptState(_Response):
    conversation_id: uuid.UUID
    read_through_seq: int
    delivered_through_seq: int
    updated_at: datetime
