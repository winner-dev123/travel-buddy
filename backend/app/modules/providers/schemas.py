"""Provider API shapes (contract tag ``providers``; docs/18 §4).

Public schemas (``ProviderSummary``, ``ProviderProfile``, ``Offering``, ``ProviderReview``) never
carry legal name, registration number, documents, staff notes or the member list (PROV-002).
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from typing import Literal, Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.pagination import PageInfo
from app.modules.destinations.schemas import DestinationSummary
from app.modules.media.schemas import MediaRef
from app.modules.profiles.schemas import UserSummary

KindName = Literal["guide", "company"]
StatusName = Literal[
    "draft", "submitted", "changes_requested", "approved", "rejected", "suspended", "deactivated"
]
RoleName = Literal["owner", "manager", "agent"]
InvitableRole = Literal["manager", "agent"]
MemberStatusName = Literal["invited", "active"]
SpecialtyName = Literal[
    "city_tours",
    "history_culture",
    "food_drink",
    "nature",
    "adventure",
    "water_activities",
    "nightlife",
    "photography",
    "art_museums",
    "family",
    "wellness",
    "accessible_travel",
    "transfers",
    "multi_day",
]
DocumentKindName = Literal[
    "identity",
    "tourism_registry",
    "guide_license",
    "business_registration",
    "insurance",
    "other",
]
DocumentStatusName = Literal["pending", "accepted", "rejected"]
OfferingKindName = Literal["tour", "activity", "transfer", "package", "class", "other"]
OfferingStatusName = Literal["draft", "published", "archived", "removed"]
PriceUnitName = Literal["per_person", "per_group"]
InquiryStatusName = Literal[
    "open", "accepted", "declined", "withdrawn", "expired", "completed", "cancelled"
]
SideName = Literal["traveler", "provider"]
DecisionName = Literal["approve", "request_changes", "reject"]

# BCP 47 language with an optional region: "pt", "pt-BR".
LANGUAGE = r"^[a-z]{2,3}(-[A-Z]{2})?$"
COUNTRY = r"^[A-Z]{2}$"
CURRENCY = r"^[A-Z]{3}$"


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Response(BaseModel):
    model_config = ConfigDict(frozen=True)


def _unique[T](values: list[T]) -> list[T]:
    seen: list[T] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return seen


def _check_languages(value: list[str] | None) -> list[str] | None:
    if value is None:
        return None
    for code in value:
        if not re.match(LANGUAGE, code):
            raise ValueError(f"{code!r} is not a language code like 'en' or 'pt-BR'.")
    return _unique(value)


# ───────────────────────────── requests ─────────────────────────────


class _ProviderFields(_Request):
    display_name: str | None = Field(default=None, min_length=2, max_length=80)
    legal_name: str | None = Field(default=None, min_length=2, max_length=200)
    tagline: str | None = Field(default=None, max_length=120)
    about: str | None = Field(default=None, max_length=4000)
    country_code: str | None = Field(default=None, pattern=COUNTRY)
    base_destination_id: uuid.UUID | None = None
    languages: list[str] | None = Field(default=None, max_length=12)
    specialties: list[SpecialtyName] | None = Field(default=None, max_length=8)
    years_experience: int | None = Field(default=None, ge=0, le=80)
    website_url: AnyHttpUrl | None = None
    registration_number: str | None = Field(default=None, min_length=2, max_length=64)
    logo_media_id: uuid.UUID | None = None
    cover_media_id: uuid.UUID | None = None

    @field_validator("languages")
    @classmethod
    def _languages(cls, value: list[str] | None) -> list[str] | None:
        return _check_languages(value)

    @field_validator("specialties")
    @classmethod
    def _specialties(cls, value: list[SpecialtyName] | None) -> list[SpecialtyName] | None:
        return _unique(value) if value is not None else None

    @field_validator("website_url")
    @classmethod
    def _website(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        if value is not None and len(str(value)) > 300:
            raise ValueError("Use a shorter web address (up to 300 characters).")
        return value


class CreateProviderRequest(_ProviderFields):
    kind: KindName
    display_name: str = Field(min_length=2, max_length=80)
    country_code: str = Field(pattern=COUNTRY)
    base_destination_id: uuid.UUID


class UpdateProviderRequest(_ProviderFields):
    """Only the fields sent change; ``null`` clears an optional field. After the first
    approval ``kind``, ``legal_name``, ``country_code`` and ``registration_number`` are locked."""

    kind: KindName | None = None


class ServiceAreasRequest(_Request):
    destination_ids: list[uuid.UUID] = Field(max_length=20)

    @field_validator("destination_ids")
    @classmethod
    def _dedupe(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        return _unique(value)


class AddDocumentRequest(_Request):
    kind: DocumentKindName
    media_id: uuid.UUID
    number: str | None = Field(default=None, min_length=1, max_length=64)
    issuing_country: str | None = Field(default=None, pattern=COUNTRY)
    expires_on: date | None = None


class SubmitProviderRequest(_Request):
    terms_version: str = Field(min_length=1, max_length=40)


class InviteMemberRequest(_Request):
    handle: str = Field(min_length=1, max_length=40)
    role: InvitableRole


class ChangeMemberRoleRequest(_Request):
    role: InvitableRole


class _OfferingFields(_Request):
    kind: OfferingKindName | None = None
    title: str | None = Field(default=None, min_length=3, max_length=100)
    description: str | None = Field(default=None, max_length=4000)
    destination_id: uuid.UUID | None = None
    duration_minutes: int | None = Field(default=None, ge=15, le=43200)
    price_from_minor: int | None = Field(default=None, ge=0, le=100_000_000_00)
    currency: str | None = Field(default=None, pattern=CURRENCY)
    price_unit: PriceUnitName | None = None
    max_group_size: int | None = Field(default=None, ge=1, le=500)
    languages: list[str] | None = Field(default=None, max_length=12)
    cover_media_id: uuid.UUID | None = None

    @field_validator("languages")
    @classmethod
    def _languages(cls, value: list[str] | None) -> list[str] | None:
        return _check_languages(value)


class CreateOfferingRequest(_OfferingFields):
    kind: OfferingKindName
    title: str = Field(min_length=3, max_length=100)
    destination_id: uuid.UUID

    @model_validator(mode="after")
    def _price(self) -> Self:
        if (self.price_from_minor is None) != (self.currency is None):
            raise ValueError("Send price_from_minor and currency together.")
        return self


class UpdateOfferingRequest(_OfferingFields):
    pass


class CreateInquiryRequest(_Request):
    offering_id: uuid.UUID | None = None
    start_date: date | None = None
    end_date: date | None = None
    flexible_dates: bool = False
    party_size: int = Field(ge=1, le=50)
    message: str = Field(min_length=10, max_length=2000)

    @model_validator(mode="after")
    def _dates(self) -> Self:
        if self.end_date is not None and self.start_date is None:
            raise ValueError("Send start_date with end_date.")
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date can't be before start_date.")
        if self.start_date is None and not self.flexible_dates:
            raise ValueError("Pick a date, or say your dates are flexible.")
        return self


class DeclineInquiryRequest(_Request):
    reason: str | None = Field(default=None, max_length=500)


class CreateReviewRequest(_Request):
    rating: int = Field(ge=1, le=5)
    body: str | None = Field(default=None, max_length=2000)


class ReplyReviewRequest(_Request):
    body: str = Field(min_length=1, max_length=2000)


class DocumentDecision(_Request):
    id: uuid.UUID
    status: Literal["accepted", "rejected"]


class ProviderDecisionRequest(_Request):
    decision: DecisionName
    note: str | None = Field(default=None, max_length=1000)
    documents: list[DocumentDecision] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _note(self) -> Self:
        if self.decision != "approve" and not (self.note or "").strip():
            raise ValueError("Tell the applicant what to change or why (note).")
        return self


class SuspendProviderRequest(_Request):
    reason: str = Field(min_length=3, max_length=1000)


# ───────────────────────────── responses ─────────────────────────────


class Membership(_Response):
    role: RoleName
    status: MemberStatusName


class ProviderSummary(_Response):
    """A provider card (lists, chat headers, requests)."""

    id: uuid.UUID
    slug: str
    kind: KindName
    status: StatusName
    display_name: str
    tagline: str | None
    logo: MediaRef | None
    cover: MediaRef | None
    base_destination: DestinationSummary | None
    languages: list[str]
    specialties: list[SpecialtyName]
    rating_average: float | None
    rating_count: int
    # "Verified by Travel Buddy" since (first approval).
    verified_at: datetime | None
    # Average time to the first answer; shown after a few answered requests.
    response_time_seconds: int | None


class ProviderProfile(ProviderSummary):
    about: str | None
    years_experience: int | None
    website_url: str | None
    service_areas: list[DestinationSummary]
    published_offering_count: int
    membership: Membership | None = None


class ProviderWorkspace(ProviderProfile):
    """What a provider's own members see (owner and managers edit it)."""

    country_code: str
    legal_name: str | None
    registration_number: str | None
    review_note: str | None
    suspended_reason: str | None
    submitted_at: datetime | None
    decided_at: datetime | None
    locked_fields: list[str]
    terms_version: str  # the current Provider Terms version to accept when submitting
    terms_accepted_version: str | None
    missing_for_submit: list[str]
    inquiry_count: int
    response_count: int
    version: int
    created_at: datetime


class ProviderPage(_Response):
    data: list[ProviderSummary]
    page: PageInfo


class ProviderMembershipOut(_Response):
    provider: ProviderSummary
    role: RoleName
    status: MemberStatusName
    invited_by: UserSummary | None
    created_at: datetime


class ProviderMembershipList(_Response):
    data: list[ProviderMembershipOut]


class DocumentOut(_Response):
    """Never carries a file URL for members (PROV-004)."""

    id: uuid.UUID
    kind: DocumentKindName
    number: str | None
    issuing_country: str | None
    expires_on: date | None
    status: DocumentStatusName
    file_available: bool
    created_at: datetime
    decided_at: datetime | None


class DocumentList(_Response):
    data: list[DocumentOut]


class MemberOut(_Response):
    user: UserSummary | None
    role: RoleName
    status: MemberStatusName
    created_at: datetime
    accepted_at: datetime | None


class MemberList(_Response):
    data: list[MemberOut]


class Price(_Response):
    amount_minor: int
    currency: str
    unit: PriceUnitName | None
    indicative: Literal[True] = True


class OfferingOut(_Response):
    id: uuid.UUID
    provider: ProviderSummary
    status: OfferingStatusName
    kind: OfferingKindName
    title: str
    description: str | None
    destination: DestinationSummary | None
    duration_minutes: int | None
    price_from: Price | None
    max_group_size: int | None
    languages: list[str]
    cover: MediaRef | None
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime
    version: int


class OfferingPage(_Response):
    data: list[OfferingOut]
    page: PageInfo


class OfferingRef(_Response):
    id: uuid.UUID
    title: str
    kind: OfferingKindName


class InquiryOut(_Response):
    id: uuid.UUID
    provider: ProviderSummary
    traveler: UserSummary | None
    offering: OfferingRef | None
    start_date: date | None
    end_date: date | None
    flexible_dates: bool
    party_size: int
    message: str
    status: InquiryStatusName
    decline_reason: str | None
    conversation_id: uuid.UUID | None
    first_response_at: datetime | None
    decided_at: datetime | None
    completed_at: datetime | None
    viewer_side: SideName
    can_review: bool
    review_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    version: int


class InquiryPage(_Response):
    data: list[InquiryOut]
    page: PageInfo


class ReviewReply(_Response):
    body: str
    replied_at: datetime


class ReviewOut(_Response):
    id: uuid.UUID
    provider_id: uuid.UUID
    rating: int
    body: str | None
    # None when the author's account was erased: clients show "Former traveler".
    author: UserSummary | None
    reply: ReviewReply | None
    created_at: datetime


class ReviewPage(_Response):
    data: list[ReviewOut]
    page: PageInfo


# ───────────────────────────── staff (docs/18 §4) ─────────────────────────────


class AdminProviderSummary(_Response):
    id: uuid.UUID
    kind: KindName
    status: StatusName
    display_name: str
    country_code: str
    owner: UserSummary | None
    submitted_at: datetime | None
    decided_at: datetime | None
    created_at: datetime


class AdminProviderPage(_Response):
    data: list[AdminProviderSummary]
    page: PageInfo


class AdminDocument(DocumentOut):
    decided_by: uuid.UUID | None
    uploaded_by: uuid.UUID | None


class AdminProvider(_Response):
    provider: ProviderWorkspace
    owner: UserSummary | None
    members: list[MemberOut]
    documents: list[AdminDocument]
    decided_by: uuid.UUID | None
    open_report_count: int


class DocumentFileLink(_Response):
    url: str
    expires_at: datetime
