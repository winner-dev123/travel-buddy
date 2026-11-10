"""Guide and audio tour shapes (contract ``GuideSummary``, ``Guide``, ``AudioTourSummary``,
``AudioTour``) and the authored section format they are validated against."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.billing.schemas import QuotaStatusOut
from app.modules.destinations.schemas import DestinationSummary, PlaceSummary
from app.modules.media.schemas import MediaRef

Tier = Literal["free", "premium", "purchasable"]


class FaqItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    question: str = Field(min_length=1, max_length=300)
    answer_markdown: str = Field(min_length=1, max_length=4000)


class GuideSection(BaseModel):
    """One authored section; ``faq`` sections carry structured ``faq_items`` (GUIDE-006)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=60)
    kind: Literal["prose", "faq"] = "prose"
    heading: str = Field(min_length=1, max_length=200)
    body_markdown: str = Field(default="", max_length=20_000)
    place_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    faq_items: list[FaqItem] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.kind == "faq" and not self.faq_items:
            raise ValueError("faq sections need faq_items")
        if self.kind == "prose" and not self.body_markdown.strip():
            raise ValueError("prose sections need body_markdown")
        if self.kind == "prose" and self.faq_items:
            raise ValueError("only faq sections have faq_items")
        return self


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True)


class GuideSummary(_Out):
    id: uuid.UUID
    destination_id: uuid.UUID
    locale: str
    title: str
    summary: str
    tier: Tier
    entitled: bool
    product_id: uuid.UUID | None
    version: int
    published_at: datetime


class GuideSummaryList(_Out):
    data: list[GuideSummary]


class Guide(_Out):
    id: uuid.UUID
    destination: DestinationSummary
    locale: str
    title: str
    summary: str
    sections: list[GuideSection]
    tier: Tier
    version: int
    content_license: str
    attribution: str | None
    published_at: datetime
    updated_at: datetime


class AudioTourSummary(_Out):
    id: uuid.UUID
    destination_id: uuid.UUID
    locale: str
    title: str
    description: str
    tier: Tier
    entitled: bool
    total_duration_s: int
    stop_count: int
    version: int


class AudioTourSummaryList(_Out):
    data: list[AudioTourSummary]


class AudioTourStop(_Out):
    id: uuid.UUID
    sort_order: int
    place: PlaceSummary
    title: str
    audio: MediaRef
    transcript: str | None
    trigger_radius_m: int
    duration_s: int


class AudioTour(_Out):
    id: uuid.UUID
    destination: DestinationSummary
    locale: str
    title: str
    description: str
    tier: Tier
    version: int
    total_duration_s: int
    stops: list[AudioTourStop]
    content_license: str


PackageKind = Literal["guide", "audio_tour", "map_region", "bundle"]


class OfflinePackageSummary(_Out):
    id: uuid.UUID
    destination_id: uuid.UUID
    locale: str
    kind: PackageKind
    version: int
    total_bytes: int
    tier: Tier
    entitled: bool
    min_app_version: str
    license_expires_at: datetime | None
    published_at: datetime


class OfflinePackageList(_Out):
    data: list[OfflinePackageSummary]


class DownloadInfo(_Out):
    base_url: str
    expires_at: datetime


class LicenseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str = Field(min_length=8, max_length=128)


class OfflinePackageLicenseOut(_Out):
    id: uuid.UUID
    package_id: uuid.UUID
    device_id: str
    granted_at: datetime
    expires_at: datetime | None
    # Kept as the exact signed dict: re-serializing could change the signed bytes.
    manifest: dict[str, Any]
    download: DownloadInfo
    quota: QuotaStatusOut


class OfflinePackageLicenseSummary(_Out):
    id: uuid.UUID
    package: OfflinePackageSummary
    device_id: str
    granted_at: datetime
    expires_at: datetime | None


class OfflineLicenseList(_Out):
    data: list[OfflinePackageLicenseSummary]
