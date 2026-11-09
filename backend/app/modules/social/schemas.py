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


class UserSummary(_Response):
    id: uuid.UUID
    handle: str
    display_name: str
    avatar: None = None  # MediaRef once media lands (BL-1.08)


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
    media: list[Any] = Field(default_factory=list)  # MediaRef with BL-1.08
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
