"""Request/response models for browse and upcoming destinations (mirror the contract)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from app.modules.destinations.schemas import Destination, DestinationSummary, GeoPoint


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _Response(BaseModel):
    model_config = ConfigDict(frozen=True)


class SetBrowseDestinationRequest(_Request):
    destination_id: uuid.UUID


class BrowseDestination(_Response):
    destination: DestinationSummary
    selected_at: datetime


class CreateUpcomingDestinationRequest(_Request):
    destination_id: uuid.UUID
    start_date: date | None = None
    end_date: date | None = None
    share_for_discovery: StrictBool = False


class UpcomingDestination(_Response):
    id: uuid.UUID
    destination: DestinationSummary
    start_date: date | None
    end_date: date | None
    share_for_discovery: bool
    created_at: datetime


class UpcomingDestinationList(_Response):
    data: list[UpcomingDestination]


class _DiscoveryRequestBase(_Request):
    duration_hours: int = Field(default=24, ge=1, le=72)
    visibility: Literal["visible", "invisible"] = "visible"
    travel_start_date: date | None = None
    travel_end_date: date | None = None

    @model_validator(mode="after")
    def _dates_in_order(self) -> Self:
        start, end = self.travel_start_date, self.travel_end_date
        if start and end and end < start:
            raise ValueError("travel_end_date must not be before travel_start_date")
        return self


class DiscoveryByDestinationRequest(_DiscoveryRequestBase):
    mode: Literal["destination"]
    destination_id: uuid.UUID
    area_destination_id: uuid.UUID | None = None


class GeoPointInput(_Request):
    """Write-only: resolved once, never stored, logged or echoed."""

    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=100_000)
    captured_at: datetime | None = None  # when the device took the fix (LOC-007)

    def __repr__(self) -> str:  # keep coordinates out of logs and tracebacks
        return "GeoPointInput(<redacted>)"

    __str__ = __repr__


class DiscoveryByGpsRequest(_DiscoveryRequestBase):
    mode: Literal["gps"]
    point: GeoPointInput


SetDiscoverySessionRequest = Annotated[
    DiscoveryByDestinationRequest | DiscoveryByGpsRequest, Field(discriminator="mode")
]


class DiscoverySessionOut(_Response):
    """Resolved destinations only, never coordinates."""

    id: uuid.UUID
    destination: DestinationSummary
    area: DestinationSummary | None
    granularity: Literal["city", "neighborhood"]
    source: Literal["gps_resolved", "manual"]
    visibility: Literal["visible", "invisible"]
    travel_start_date: date | None
    travel_end_date: date | None
    started_at: datetime
    expires_at: datetime


class ApproximateLocation(_Response):
    """Where the caller seems to be, from their IP address (LOC-010). About a city, never finer:
    ``center`` is the covered city's public centroid, or the database's city point rounded to
    0.01 degrees. Only ever describes the caller."""

    source: Literal["ip"]
    precision: Literal["city", "country"]
    label: str
    center: GeoPoint
    destination: Destination | None
