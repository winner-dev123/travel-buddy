"""Request/response models for posts (mirror the contract)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StringConstraints,
    model_serializer,
    model_validator,
)

from app.core.i18n import LOCALE_TAG_PATTERN
from app.modules.destinations.schemas import DestinationSummary
from app.modules.media.schemas import MediaRef
from app.modules.profiles.schemas import UserSummary as UserSummary  # re-export

PostKindName = Literal[
    "text",
    "photo",
    "video",
    "story",
    "attraction_recommendation",
    "restaurant_recommendation",
    "review",
    "tip",
    "itinerary_summary",
    "experience",
]
VisibilityName = Literal["public", "followers", "connections", "private"]
PrecisionName = Literal["none", "destination", "place"]
ReactionName = Literal["like", "love", "helpful", "wow"]
ModerationName = Literal["pending", "approved", "limited", "removed"]
LocaleTag = Annotated[str, StringConstraints(pattern=LOCALE_TAG_PATTERN, max_length=35)]
Tag = Annotated[str, StringConstraints(min_length=1, max_length=40)]


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Response(BaseModel):
    model_config = ConfigDict(frozen=True)


class CreatePostRequest(_Request):
    kind: PostKindName
    body: str = Field(max_length=5000)
    language: LocaleTag | None = None
    visibility: VisibilityName
    media_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)
    location_precision: PrecisionName
    destination_id: uuid.UUID | None = None
    place_id: uuid.UUID | None = None
    travel_date: date | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    trip_id: uuid.UUID | None = None
    tags: list[Tag] = Field(default_factory=list, max_length=10)


class UpdatePostRequest(_Request):
    """Absent = unchanged; ``null`` clears the nullable fields only."""

    nullable_fields: ClassVar[frozenset[str]] = frozenset(
        {"destination_id", "place_id", "travel_date", "rating"}
    )

    body: str | None = Field(default=None, max_length=5000)
    visibility: VisibilityName | None = None
    location_precision: PrecisionName | None = None
    destination_id: uuid.UUID | None = None
    place_id: uuid.UUID | None = None
    travel_date: date | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    tags: list[Tag] | None = Field(default=None, max_length=10)

    @model_validator(mode="after")
    def _presence(self) -> Any:
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        for name in self.model_fields_set:
            if getattr(self, name) is None and name not in self.nullable_fields:
                raise ValueError(f"{name} cannot be null")
        return self

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class PostCounts(_Response):
    reactions: int
    comments: int
    bookmarks: int
    shares: int
    reactions_by_type: dict[ReactionName, int]


class PostViewerState(_Response):
    reaction: ReactionName | None
    bookmarked: bool
    is_author: bool
    can_edit: bool
    can_delete: bool
    can_comment: bool


class Post(_Response):
    id: uuid.UUID
    author: UserSummary
    kind: PostKindName
    body: str
    language: str
    visibility: VisibilityName
    location_precision: PrecisionName
    primary_destination: DestinationSummary | None
    place: None = None  # PlaceSummary with the places module (Phase 4)
    travel_date: date | None
    rating: int | None
    trip_id: uuid.UUID | None
    tags: list[str]
    media: list[MediaRef] = Field(default_factory=list)
    published_at: datetime
    edited_at: datetime | None
    counts: PostCounts
    indexable: bool
    viewer: PostViewerState
    moderation_state: ModerationName | None = None  # author only

    @model_serializer(mode="wrap")
    def _omit_moderation_for_others(self, handler: SerializerFunctionWrapHandler) -> Any:
        data = handler(self)
        if isinstance(data, dict) and data.get("moderation_state") is None:
            data.pop("moderation_state", None)  # contract: present only for the author
        return data

    def as_json(self) -> dict[str, Any]:
        data: dict[str, Any] = self.model_dump(mode="json")
        return data


class ReactionRequest(_Request):
    reaction: ReactionName


class ReactionResult(_Response):
    reaction: ReactionName
    counts: PostCounts


class ReactionOut(_Response):
    user: UserSummary
    reaction: ReactionName
    created_at: datetime


class CreateCommentRequest(_Request):
    body: str = Field(min_length=1, max_length=2000)
    parent_comment_id: uuid.UUID | None = None


class UpdateCommentRequest(_Request):
    body: str = Field(min_length=1, max_length=2000)


class CommentViewer(_Response):
    can_edit: bool
    can_delete: bool


class CommentOut(_Response):
    id: uuid.UUID
    post_id: uuid.UUID
    parent_comment_id: uuid.UUID | None
    author: UserSummary | None  # null for tombstones
    body: str | None
    language: str
    reply_count: int
    deleted: bool
    created_at: datetime
    edited_at: datetime | None
    viewer: CommentViewer


class ShareRequest(_Request):
    channel: Literal["system_share_sheet", "copy_link", "message"] | None = None


class ShareLink(_Response):
    url: str


class ProfileCounts(_Response):
    posts: int
    followers: int
    following: int


class PublicProfile(_Response):
    """Contract ``PublicProfile``: another user's profile as the viewer may see it."""

    id: uuid.UUID
    handle: str
    display_name: str
    avatar: MediaRef | None = None
    bio: str | None
    home_country_code: str | None
    travel_styles: list[str]
    interests: list[str]
    languages_spoken: list[str]
    account_visibility: Literal["public", "private"]
    is_restricted: bool
    indexable: bool
    counts: ProfileCounts | None
    badges: list[dict[str, object]] = Field(default_factory=list)
    relationship: Literal[
        "none", "request_pending", "request_received", "connected", "declined", "blocked"
    ] = "none"
    follow_status: Literal["none", "following", "requested"]
    can_request_connection: bool = False  # connections arrive in Phase 2
    can_message: bool = False  # messaging arrives in Phase 2


class FollowState(_Response):
    status: Literal["following", "requested"]
