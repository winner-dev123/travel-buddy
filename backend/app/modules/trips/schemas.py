"""Trip API shapes (contract ``Trip``, ``TripSummary``, itinerary inputs, sync)."""

from __future__ import annotations

import datetime as dt
import uuid
from datetime import date, datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.pagination import PageInfo
from app.modules.destinations.schemas import DestinationSummary
from app.modules.profiles.schemas import UserSummary

Visibility = Literal["private", "connections", "group", "public"]
Status = Literal["planning", "active", "completed", "archived"]
Kind = Literal["activity", "meal", "transit", "lodging", "note", "free_time"]
HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Response(BaseModel):
    model_config = ConfigDict(frozen=True)


class CreateTripRequest(_Request):
    title: str = Field(min_length=1, max_length=100)
    start_date: date
    end_date: date
    destination_ids: list[uuid.UUID] = Field(max_length=10)
    visibility: Visibility = "private"
    group_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _dates(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class UpdateTripRequest(_Request):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    start_date: date | None = None
    end_date: date | None = None
    destination_ids: list[uuid.UUID] | None = Field(default=None, max_length=10)
    visibility: Visibility | None = None
    status: Status | None = None
    group_id: uuid.UUID | None = None


class DayInput(_Request):
    day_index: int | None = Field(default=None, ge=0)
    date: dt.date | None = None
    destination_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ItemInput(_Request):
    kind: Kind
    place_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    start_time: str | None = Field(default=None, pattern=HHMM)
    duration_minutes: int | None = Field(default=None, ge=0, le=1440)
    after_item_id: uuid.UUID | None = None


class ItemPatch(_Request):
    kind: Kind | None = None
    place_id: uuid.UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    start_time: str | None = Field(default=None, pattern=HHMM)
    duration_minutes: int | None = Field(default=None, ge=0, le=1440)
    day_id: uuid.UUID | None = None
    after_item_id: uuid.UUID | None = None


class SyncOperation(_Request):
    op_id: uuid.UUID
    entity: Literal["trip", "day", "item"]
    action: Literal["create", "update", "delete"]
    entity_id: uuid.UUID
    parent_id: uuid.UUID | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    client_updated_at: datetime


class SyncRequest(_Request):
    base_version: int = Field(ge=1)
    operations: list[SyncOperation] = Field(max_length=200)


class SourceAttribution(_Response):
    kind: Literal["catalog_place", "destination_guide", "licensed_provider", "ai_general_knowledge"]
    ref_id: uuid.UUID | None = None
    provider: str | None = None
    license: str | None = None
    url: str | None = None
    retrieved_at: datetime | None = None


class ItemOut(_Response):
    id: uuid.UUID
    sort_order: str
    kind: Kind
    place: None = None  # catalog places arrive with BL-4.01
    title: str
    notes: str | None
    start_time: str | None
    duration_minutes: int | None
    origin: Literal["user", "ai"]
    ai_confidence: float | None
    unverified: bool
    source_attribution: list[SourceAttribution]
    data_freshness_at: datetime | None
    updated_at: datetime


class DayOut(_Response):
    id: uuid.UUID
    day_index: int
    date: dt.date | None
    destination: DestinationSummary | None
    notes: str | None
    items: list[ItemOut]


class TripDestinationOut(_Response):
    destination: DestinationSummary
    start_date: date | None
    end_date: date | None
    sort_order: int


class CollaboratorOut(_Response):
    user: UserSummary
    role: Literal["editor", "viewer"]


class TripOut(_Response):
    id: uuid.UUID
    owner: UserSummary
    title: str
    start_date: date
    end_date: date
    visibility: Visibility
    group_id: uuid.UUID | None
    origin: Literal["manual", "ai_generated", "ai_assisted"]
    status: Status
    destinations: list[TripDestinationOut]
    days: list[DayOut]
    collaborators: list[CollaboratorOut]
    version: int
    created_at: datetime
    updated_at: datetime


class TripSummary(_Response):
    id: uuid.UUID
    title: str
    start_date: date
    end_date: date
    status: Status
    visibility: Visibility
    origin: Literal["manual", "ai_generated", "ai_assisted"]
    destinations: list[DestinationSummary]
    role: Literal["owner", "editor", "viewer"]
    updated_at: datetime


class TripSummaryPage(_Response):
    data: list[TripSummary]
    page: PageInfo


class SyncConflict(_Response):
    op_id: uuid.UUID
    entity: Literal["trip", "day", "item"]
    entity_id: uuid.UUID
    reason: Literal["modified_on_server", "deleted_on_server", "invalid"]
    server_state: dict[str, Any] | None


class SyncResult(_Response):
    trip: TripOut
    applied_op_ids: list[uuid.UUID]
    conflicts: list[SyncConflict]
