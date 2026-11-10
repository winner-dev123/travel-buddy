"""AI API shapes (contract `GenerateItineraryRequest`, `ItineraryProposal`, `AIGeneration`)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.billing.schemas import QuotaStatusOut
from app.modules.destinations.schemas import DestinationSummary, PlaceSummary

TravelStyle = Literal[
    "adventure",
    "backpacking",
    "luxury",
    "food",
    "culture",
    "photography",
    "digital_nomad",
    "nature",
    "family",
]
PlaceCategory = Literal[
    "attraction",
    "restaurant",
    "cafe",
    "bar",
    "museum",
    "beach",
    "trail",
    "viewpoint",
    "park",
    "market",
    "lodging",
    "transit_hub",
    "other",
]
ItemKind = Literal["activity", "meal", "transit", "lodging", "note", "free_time"]
HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"


class Party(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adults: int = Field(default=1, ge=1, le=20)
    children: int = Field(default=0, ge=0, le=10)


class GenerateItineraryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    destination_id: uuid.UUID
    start_date: date
    end_date: date
    interests: list[str] = Field(default_factory=list, max_length=15)
    travel_styles: list[TravelStyle] = Field(default_factory=list, max_length=9)
    pace: Literal["relaxed", "moderate", "packed"] = "moderate"
    budget_level: Literal["budget", "moderate", "premium"] = "moderate"
    party: Party = Field(default_factory=Party)
    preferences: str | None = Field(default=None, max_length=500)
    include_social_opportunities: bool = False

    @field_validator("interests")
    @classmethod
    def _interests(cls, value: list[str]) -> list[str]:
        cleaned = [v.strip() for v in value]
        if any(not v or len(v) > 40 for v in cleaned):
            raise ValueError("interests are 1-40 characters each")
        if len({v.casefold() for v in cleaned}) != len(cleaned):
            raise ValueError("interests must be unique")
        return cleaned

    @field_validator("travel_styles")
    @classmethod
    def _styles(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("travel_styles must be unique")
        return value

    @model_validator(mode="after")
    def _dates(self) -> Self:
        if self.start_date > self.end_date:
            raise ValueError("start_date must be on or before end_date")
        return self


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True)


class SourceAttribution(_Out):
    kind: Literal["catalog_place", "destination_guide", "licensed_provider", "ai_general_knowledge"]
    ref_id: uuid.UUID | None = None
    provider: str | None = None
    license: str | None = None
    url: str | None = None
    retrieved_at: datetime | None = None


class ProposedActivity(_Out):
    kind: ItemKind
    title: str
    description: str
    place_id: uuid.UUID | None
    unverified: bool
    suggested_start_time: str | None
    estimated_duration_minutes: int
    category: PlaceCategory | None
    confidence: float
    rationale: str
    social_opportunity: bool
    source_attribution: list[SourceAttribution]
    place: PlaceSummary | None = None  # joined from the licensed catalog, never generated
    place_data_freshness_at: datetime | None = None


class ProposedDay(_Out):
    day_index: int
    date: date
    destination_id: uuid.UUID
    theme: str | None
    items: list[ProposedActivity]


class Itinerary(_Out):
    destination: DestinationSummary
    start_date: date
    end_date: date
    time_zone: str
    days: list[ProposedDay]
    sources: list[SourceAttribution]
    generated_at: datetime


class Freshness(_Out):
    catalog_data_as_of: datetime | None = None


class ItineraryProposal(_Out):
    itinerary: Itinerary
    warnings: list[str]
    disclaimer: str
    prompt_version: str
    confidence: float
    freshness: Freshness = Field(default_factory=Freshness)


class AIGenerationOut(_Out):
    id: uuid.UUID
    feature: Literal["itinerary_generate", "trip_replan"]
    status: Literal["pending", "succeeded", "failed"]
    created_at: datetime
    completed_at: datetime | None
    result: ItineraryProposal | None
    error: dict[str, Any] | None
    quota: QuotaStatusOut


class TranslationOut(_Out):
    """Contract ``Translation``: always labelled as machine-made (I18N-006)."""

    post_id: uuid.UUID
    source_language: str
    target_language: str
    text: str
    machine_translated: Literal[True] = True
    provider_attribution: str | None


class ReplanConstraints(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keep_item_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    avoid_categories: list[PlaceCategory] = Field(default_factory=list, max_length=13)
    pace: Literal["relaxed", "moderate", "packed"] | None = None


class ReplanTripRequest(BaseModel):
    """Contract ``ReplanTripRequest`` (AI-005)."""

    model_config = ConfigDict(extra="forbid")

    instruction: str = Field(min_length=3, max_length=500)
    base_version: int = Field(ge=1)
    day_indexes: list[int] | None = Field(default=None, max_length=90)
    constraints: ReplanConstraints = Field(default_factory=ReplanConstraints)

    @field_validator("day_indexes")
    @classmethod
    def _indexes(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and any(i < 0 for i in value):
            raise ValueError("day indexes start at 0")
        return value


class ReplanItem(BaseModel):
    id: uuid.UUID
    title: str
    kind: str
    start_time: str | None
    duration_minutes: int | None
    place_id: uuid.UUID | None


class ReplanDay(BaseModel):
    day_index: int
    items: list[ReplanItem]


class ReplanParams(BaseModel):
    """What a replan generation stores until it is answered (the trip as it was requested)."""

    trip_id: uuid.UUID
    destination_id: uuid.UUID
    start_date: date
    end_date: date
    instruction: str
    day_indexes: list[int]
    pace: Literal["relaxed", "moderate", "packed"]
    avoid_categories: list[str]
    keep_item_ids: list[uuid.UUID]
    current: list[ReplanDay]
