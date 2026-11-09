"""Request/response models for browse and upcoming destinations (mirror the contract)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, StrictBool

from app.modules.destinations.schemas import DestinationSummary


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
