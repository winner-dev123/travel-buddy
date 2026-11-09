"""Discovery shapes (contract ``TravelerCard``, ``TravelerPresence``). No coordinates,
distances or activity times exist in these models (T-LOC-01, DISC-004)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.modules.destinations.schemas import DestinationSummary
from app.modules.profiles.schemas import UserSummary


class _Response(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Presence(_Response):
    kind: Literal["here_now", "upcoming"]
    destination: DestinationSummary
    area: DestinationSummary | None
    travel_start_date: date | None
    travel_end_date: date | None


class Shared(_Response):
    travel_styles: list[str]
    interests: list[str]
    languages: list[str]


class TravelerCard(_Response):
    user: UserSummary
    bio_snippet: str | None
    travel_styles: list[str]
    interests: list[str]
    languages_spoken: list[str]
    presence: Presence
    shared: Shared
    compatibility: Literal["high", "medium", "low"]
    relationship: Literal[
        "none", "request_pending", "request_received", "connected", "declined", "blocked"
    ]
    can_request_connection: bool
