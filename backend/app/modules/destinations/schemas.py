"""Public response models (mirror contracts/openapi/openapi.yaml destination schemas)."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
    cover: None = None  # MediaRef once editorial media lands (BL-1.08, DEST-007)


class Destination(DestinationSummary):
    parent_id: uuid.UUID | None
    ancestors: list[DestinationSummary]
    centroid: GeoPoint
    time_zone: str
    is_featured: bool
    has_children: bool
    has_guides: bool
