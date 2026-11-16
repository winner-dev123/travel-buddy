"""Pure rules for providers (ADR-0036, docs/18 §2): state machines, team rights, ranking.

No I/O here: the service loads rows, asks these functions, and writes the outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Final

# Bumped when the Provider Terms text changes; applicants accept the current version (PROV-003).
PROVIDER_TERMS_VERSION: Final = "2026-11-16"


class ProviderKind(StrEnum):
    GUIDE = "guide"
    COMPANY = "company"


class ProviderStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"


class MemberRole(StrEnum):
    OWNER = "owner"
    MANAGER = "manager"
    AGENT = "agent"


class MemberStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"


class Specialty(StrEnum):
    CITY_TOURS = "city_tours"
    HISTORY_CULTURE = "history_culture"
    FOOD_DRINK = "food_drink"
    NATURE = "nature"
    ADVENTURE = "adventure"
    WATER_ACTIVITIES = "water_activities"
    NIGHTLIFE = "nightlife"
    PHOTOGRAPHY = "photography"
    ART_MUSEUMS = "art_museums"
    FAMILY = "family"
    WELLNESS = "wellness"
    ACCESSIBLE_TRAVEL = "accessible_travel"
    TRANSFERS = "transfers"
    MULTI_DAY = "multi_day"


class DocumentKind(StrEnum):
    IDENTITY = "identity"
    TOURISM_REGISTRY = "tourism_registry"  # e.g. CADASTUR (Brazil)
    GUIDE_LICENSE = "guide_license"
    BUSINESS_REGISTRATION = "business_registration"  # e.g. CNPJ (Brazil)
    INSURANCE = "insurance"
    OTHER = "other"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class OfferingKind(StrEnum):
    TOUR = "tour"
    ACTIVITY = "activity"
    TRANSFER = "transfer"
    PACKAGE = "package"
    CLASS = "class"
    OTHER = "other"


class OfferingStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    REMOVED = "removed"  # by staff (moderation)


class PriceUnit(StrEnum):
    PER_PERSON = "per_person"
    PER_GROUP = "per_group"


class InquiryStatus(StrEnum):
    OPEN = "open"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    WITHDRAWN = "withdrawn"
    EXPIRED = "expired"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class InquiryAction(StrEnum):
    ACCEPT = "accept"
    DECLINE = "decline"
    WITHDRAW = "withdraw"
    COMPLETE = "complete"
    CANCEL = "cancel"


class Side(StrEnum):
    TRAVELER = "traveler"
    PROVIDER = "provider"


class ReviewStatus(StrEnum):
    VISIBLE = "visible"
    REMOVED = "removed"


class Decision(StrEnum):
    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    REJECT = "reject"


# ── limits (docs/18 §3) ──
MAX_SERVICE_AREAS: Final = 20
MAX_PUBLISHED_OFFERINGS: Final = 50
MAX_SPECIALTIES: Final = 8
MAX_LANGUAGES: Final = 12
MAX_DOCUMENTS: Final = 10
INQUIRY_EXPIRY: Final = timedelta(days=14)
UNDATED_COMPLETION: Final = timedelta(days=30)
REVIEW_WINDOW: Final = timedelta(days=60)
DOCUMENT_RETENTION: Final = timedelta(days=90)
RESPONSE_STATS_MIN: Final = 3  # requests answered before "usually replies within" shows

# Fields checked by staff; they lock at the first approval (PROV-003).
LOCKED_FIELDS: Final = frozenset({"kind", "legal_name", "country_code", "registration_number"})

VISIBLE_STATUSES: Final = frozenset({ProviderStatus.APPROVED})
FINAL_STATUSES: Final = frozenset({ProviderStatus.REJECTED, ProviderStatus.DEACTIVATED})
EDITABLE_STATUSES: Final = frozenset(
    {
        ProviderStatus.DRAFT,
        ProviderStatus.SUBMITTED,
        ProviderStatus.CHANGES_REQUESTED,
        ProviderStatus.APPROVED,
        ProviderStatus.SUSPENDED,
    }
)


# ───────────────────────────── provider lifecycle ─────────────────────────────

_DECISIONS: Final = {
    Decision.APPROVE: ProviderStatus.APPROVED,
    Decision.REQUEST_CHANGES: ProviderStatus.CHANGES_REQUESTED,
    Decision.REJECT: ProviderStatus.REJECTED,
}


def can_submit(status: ProviderStatus) -> bool:
    return status in (ProviderStatus.DRAFT, ProviderStatus.CHANGES_REQUESTED)


def decision_target(status: ProviderStatus, decision: Decision) -> ProviderStatus | None:
    """Status after a staff decision, or None when the application isn't awaiting one."""
    if status is not ProviderStatus.SUBMITTED:
        return None
    return _DECISIONS[decision]


def can_suspend(status: ProviderStatus) -> bool:
    return status is ProviderStatus.APPROVED


def can_reinstate(status: ProviderStatus) -> bool:
    return status is ProviderStatus.SUSPENDED


def can_deactivate(status: ProviderStatus) -> bool:
    return status not in FINAL_STATUSES


@dataclass(frozen=True, slots=True)
class ApplicationFacts:
    kind: ProviderKind
    has_display_name: bool
    has_base_destination: bool
    language_count: int
    has_legal_name: bool
    document_kinds: frozenset[DocumentKind]
    terms_accepted: bool


def missing_for_submit(facts: ApplicationFacts) -> list[str]:
    """What still blocks a submission (``provider_incomplete.missing``), in a stable order."""
    missing: list[str] = []
    if not facts.has_display_name:
        missing.append("display_name")
    if not facts.has_base_destination:
        missing.append("base_destination_id")
    if facts.language_count < 1:
        missing.append("languages")
    if not facts.has_legal_name:
        missing.append("legal_name")
    if DocumentKind.IDENTITY not in facts.document_kinds:
        missing.append("document:identity")
    if (
        facts.kind is ProviderKind.COMPANY
        and DocumentKind.BUSINESS_REGISTRATION not in facts.document_kinds
    ):
        missing.append("document:business_registration")
    if not facts.terms_accepted:
        missing.append("terms")
    return missing


# ───────────────────────────── team rights ─────────────────────────────

_MANAGE_PROFILE: Final = frozenset({MemberRole.OWNER, MemberRole.MANAGER})


def can_manage_profile(role: MemberRole) -> bool:
    """Edit the profile, service areas, documents, offerings; submit; block travelers."""
    return role in _MANAGE_PROFILE


def can_handle_inquiries(role: MemberRole) -> bool:
    return True  # every active member answers requests (PROV-005)


def can_invite(inviter: MemberRole, role: MemberRole) -> bool:
    """Owners invite managers and agents; managers invite agents. Nobody invites an owner."""
    if role is MemberRole.OWNER:
        return False
    if inviter is MemberRole.OWNER:
        return True
    return inviter is MemberRole.MANAGER and role is MemberRole.AGENT


def can_remove(actor: MemberRole, target: MemberRole, *, is_self: bool) -> bool:
    """Anyone but the owner may leave. The owner removes anyone else; managers remove agents."""
    if target is MemberRole.OWNER:
        return False
    if is_self:
        return True
    if actor is MemberRole.OWNER:
        return True
    return actor is MemberRole.MANAGER and target is MemberRole.AGENT


# ───────────────────────────── inquiries ─────────────────────────────

# (current status, action) → (who may do it, next status)
_TRANSITIONS: Final[dict[tuple[InquiryStatus, InquiryAction], tuple[Side, InquiryStatus]]] = {
    (InquiryStatus.OPEN, InquiryAction.ACCEPT): (Side.PROVIDER, InquiryStatus.ACCEPTED),
    (InquiryStatus.OPEN, InquiryAction.DECLINE): (Side.PROVIDER, InquiryStatus.DECLINED),
    (InquiryStatus.OPEN, InquiryAction.WITHDRAW): (Side.TRAVELER, InquiryStatus.WITHDRAWN),
    (InquiryStatus.ACCEPTED, InquiryAction.COMPLETE): (Side.PROVIDER, InquiryStatus.COMPLETED),
}
# Either side may cancel an accepted request.
_CANCELLABLE: Final = frozenset({InquiryStatus.ACCEPTED})


def inquiry_transition(
    status: InquiryStatus, action: InquiryAction, side: Side
) -> InquiryStatus | None:
    """The next status, or None when ``side`` can't do ``action`` now (409)."""
    if action is InquiryAction.CANCEL:
        return InquiryStatus.CANCELLED if status in _CANCELLABLE else None
    found = _TRANSITIONS.get((status, action))
    if found is None or found[0] is not side:
        return None
    return found[1]


def service_date(start: date | None, end: date | None) -> date | None:
    return end or start


def is_expired(
    status: InquiryStatus, created_at: datetime, start: date | None, now: datetime
) -> bool:
    """An open request expires after 14 days, or once its start date has passed."""
    if status is not InquiryStatus.OPEN:
        return False
    if now - created_at >= INQUIRY_EXPIRY:
        return True
    return start is not None and start < now.date()


def is_due_for_completion(
    status: InquiryStatus,
    start: date | None,
    end: date | None,
    decided_at: datetime | None,
    now: datetime,
) -> bool:
    """Accepted requests complete a day after the service date, or 30 days after acceptance
    when no date was given."""
    if status is not InquiryStatus.ACCEPTED:
        return False
    day = service_date(start, end)
    if day is not None:
        return (now.date() - day).days >= 1
    return decided_at is not None and now - decided_at >= UNDATED_COMPLETION


def can_review(status: InquiryStatus, completed_at: datetime | None, now: datetime) -> bool:
    return (
        status is InquiryStatus.COMPLETED
        and completed_at is not None
        and now - completed_at <= REVIEW_WINDOW
    )


# ───────────────────────────── ranking (docs/18 §5) ─────────────────────────────

PRIOR_MEAN: Final = 4.0
PRIOR_WEIGHT: Final = 5


def bayesian_rating(rating_sum: int, rating_count: int) -> float:
    """Shrinks small samples toward the prior, so one 5★ review doesn't outrank 40 4.8★ ones."""
    return (rating_sum + PRIOR_MEAN * PRIOR_WEIGHT) / (rating_count + PRIOR_WEIGHT)


def average_response_seconds(total: int, count: int) -> int | None:
    if count < RESPONSE_STATS_MIN:
        return None
    return total // count


def response_rate(responded: int, received: int) -> float:
    return 0.0 if received <= 0 else min(1.0, responded / received)
