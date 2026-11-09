"""Feed request/response models (mirror the contract)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.modules.destinations.schemas import DestinationSummary

FeedSourceName = Literal["gps", "selected", "upcoming_trip", "interests", "global", "following"]


class FeedContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    destination: DestinationSummary | None
    source: FeedSourceName
    radius_km: float | None


class FeedFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    post_id: uuid.UUID
    kind: Literal["hide", "not_interested", "see_less_author"]


class FeedResult(BaseModel):
    """Internal: posts already serialized (social ``Post.as_json``) plus page info and context."""

    model_config = ConfigDict(frozen=True)

    data: list[dict[str, Any]]
    next_cursor: str | None
    has_more: bool
    reset: bool
    context: FeedContext
