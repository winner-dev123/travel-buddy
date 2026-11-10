"""Public response models (mirror contracts/openapi/openapi.yaml destination schemas)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.media.schemas import MediaRef

DestinationKindName = Literal["country", "admin_region", "city", "district", "neighborhood", "area"]
ContinentName = Literal[
    "africa",
    "asia",
    "europe",
    "middle_east",
    "north_america",
    "central_america_caribbean",
    "south_america",
    "oceania",
]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True)


class GeoPoint(_Model):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class DestinationSummary(_Model):
    id: uuid.UUID
    kind: DestinationKindName
    slug: str
    path: str
    name: str
    country_code: str
    country_name: str | None
    continent: ContinentName
    tagline: str | None
    cover: MediaRef | None = None  # editorial media with verified rights (DEST-007)


class Destination(DestinationSummary):
    parent_id: uuid.UUID | None
    ancestors: list[DestinationSummary]
    centroid: GeoPoint
    time_zone: str
    is_featured: bool
    has_children: bool
    has_guides: bool


PlaceCategoryName = Literal[
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


class PlaceSummary(_Model):
    id: uuid.UUID
    name: str
    category: PlaceCategoryName
    destination_id: uuid.UUID
    location: GeoPoint


class PlaceAttribution(_Model):
    provider: str
    license: str
    text: str
    url: str | None


class Place(PlaceSummary):
    address: dict[str, str] | None  # only the published parts (line1, locality, ...)
    attributes: dict[str, Any]
    data_freshness_at: datetime
    data_stale: bool
    attribution: PlaceAttribution
    status: Literal["active", "closed_permanently"]
