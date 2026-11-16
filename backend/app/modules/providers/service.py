"""Guides and travel companies (ADR-0036, docs/18).

``ProviderService`` serves the app routes. Module functions serve other modules: messaging's
send rights for provider chats (``chat_policy``), report evidence and moderation, the staff
console (called by the admin module inside its audited transactions), account erasure, the
data export and the housekeeping job.
"""

from __future__ import annotations

import logging
import re
import secrets
import unicodedata
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import and_, case, delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import AppError, ErrorCode, FieldError
from app.core.pagination import CursorCodec, PageInfo
from app.core.security.principal import Principal
from app.core.time import Clock
from app.modules.destinations import service as destinations
from app.modules.identity import service as identity
from app.modules.media import service as media
from app.modules.messaging import service as messaging
from app.modules.notifications import service as notifications
from app.modules.platform import service as platform
from app.modules.profiles import service as profiles
from app.modules.providers.domain import (
    DOCUMENT_RETENTION,
    EDITABLE_STATUSES,
    INQUIRY_EXPIRY,
    LOCKED_FIELDS,
    MAX_DOCUMENTS,
    MAX_PUBLISHED_OFFERINGS,
    MAX_SERVICE_AREAS,
    PRIOR_MEAN,
    PRIOR_WEIGHT,
    PROVIDER_TERMS_VERSION,
    UNDATED_COMPLETION,
    ApplicationFacts,
    Decision,
    DocumentKind,
    DocumentStatus,
    InquiryAction,
    InquiryStatus,
    MemberRole,
    MemberStatus,
    OfferingStatus,
    ProviderKind,
    ProviderStatus,
    ReviewStatus,
    Side,
    average_response_seconds,
    can_deactivate,
    can_invite,
    can_manage_profile,
    can_reinstate,
    can_remove,
    can_review,
    can_submit,
    can_suspend,
    decision_target,
    inquiry_transition,
    missing_for_submit,
)
from app.modules.providers.models import (
    Provider,
    ProviderBlock,
    ProviderDocument,
    ProviderInquiry,
    ProviderMember,
    ProviderOffering,
    ProviderReview,
    ProviderServiceArea,
)
from app.modules.providers.schemas import (
    AddDocumentRequest,
    AdminDocument,
    AdminProvider,
    AdminProviderPage,
    AdminProviderSummary,
    ChangeMemberRoleRequest,
    CreateInquiryRequest,
    CreateOfferingRequest,
    CreateProviderRequest,
    CreateReviewRequest,
    DocumentFileLink,
    DocumentList,
    DocumentOut,
    InquiryOut,
    InquiryPage,
    InviteMemberRequest,
    MemberList,
    MemberOut,
    Membership,
    OfferingOut,
    OfferingPage,
    OfferingRef,
    Price,
    ProviderDecisionRequest,
    ProviderMembershipList,
    ProviderMembershipOut,
    ProviderPage,
    ProviderProfile,
    ProviderSummary,
    ProviderWorkspace,
    ReplyReviewRequest,
    ReviewOut,
    ReviewPage,
    ReviewReply,
    ServiceAreasRequest,
    SubmitProviderRequest,
    UpdateOfferingRequest,
    UpdateProviderRequest,
)

logger = logging.getLogger(__name__)

CREATE_ROUTE = "POST /v1/providers"
INQUIRY_ROUTE = "POST /v1/providers/{id}/inquiries"
HOUSEKEEPING_JOB = "providers.housekeeping"
RESPONSE_JOB = "providers.first_response"

Preferences = Sequence[str]


# ───────────────────────────── errors ─────────────────────────────


def _not_found(what: str = "Provider") -> AppError:
    return AppError(ErrorCode.NOT_FOUND, f"{what} not found.")


def _forbidden(message: str = "You can't do that for this provider.") -> AppError:
    return AppError(ErrorCode.FORBIDDEN, message)


def _invalid(field: str, message: str, code: str = "invalid") -> AppError:
    return AppError(
        ErrorCode.VALIDATION_FAILED,
        message,
        errors=[FieldError(field=field, code=code, message=message)],
    )


def _check_version(current: int, if_match: str | None) -> None:
    """``If-Match`` is optional here; when sent it must match (lost-update protection)."""
    if if_match is not None and if_match.strip().strip('"') != str(current):
        raise AppError(
            ErrorCode.PRECONDITION_FAILED, "Someone else changed this. Reload and try again."
        )


def _slugify(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:50].strip("-") or "provider"


def _rating(provider: Provider) -> float | None:
    if provider.rating_count <= 0:
        return None
    return round(provider.rating_sum / provider.rating_count, 1)


def _verified(provider: Provider) -> datetime | None:
    return provider.approved_at if provider.status == ProviderStatus.APPROVED else None


# ───────────────────────────── output builders ─────────────────────────────


async def _summaries(
    session: AsyncSession, rows: Sequence[Provider], prefs: Preferences
) -> dict[uuid.UUID, ProviderSummary]:
    if not rows:
        return {}
    places = await destinations.summaries_by_id(
        session, list({p.base_destination_id for p in rows}), prefs
    )
    pictures = await media.refs(
        session,
        [m for p in rows for m in (p.logo_media_id, p.cover_media_id) if m is not None],
    )
    return {
        p.id: ProviderSummary(
            id=p.id,
            slug=p.slug,
            kind=p.kind,  # type: ignore[arg-type]
            status=p.status,  # type: ignore[arg-type]
            display_name=p.display_name,
            tagline=p.tagline,
            logo=pictures.get(p.logo_media_id) if p.logo_media_id else None,
            cover=pictures.get(p.cover_media_id) if p.cover_media_id else None,
            base_destination=places.get(p.base_destination_id),
            languages=list(p.languages or []),
            specialties=list(p.specialties or []),  # type: ignore[arg-type]
            rating_average=_rating(p),
            rating_count=p.rating_count,
            verified_at=_verified(p),
            response_time_seconds=average_response_seconds(
                p.response_seconds_total, p.response_count
            ),
        )
        for p in rows
    }


async def _summary(
    session: AsyncSession, provider: Provider, prefs: Preferences
) -> ProviderSummary:
    return (await _summaries(session, [provider], prefs))[provider.id]


async def _profile_fields(
    session: AsyncSession, provider: Provider, prefs: Preferences
) -> dict[str, Any]:
    summary = await _summary(session, provider, prefs)
    area_ids = list(
        await session.scalars(
            select(ProviderServiceArea.destination_id).where(
                ProviderServiceArea.provider_id == provider.id,
                ProviderServiceArea.is_base.is_(False),
            )
        )
    )
    areas = await destinations.summaries_by_id(session, area_ids, prefs)
    published = await session.scalar(
        select(func.count())
        .select_from(ProviderOffering)
        .where(
            ProviderOffering.provider_id == provider.id,
            ProviderOffering.status == OfferingStatus.PUBLISHED,
        )
    )
    return {
        **summary.model_dump(),
        "about": provider.about,
        "years_experience": provider.years_experience,
        "website_url": provider.website_url,
        "service_areas": [areas[i] for i in area_ids if i in areas],
        "published_offering_count": int(published or 0),
    }


def _membership_out(member: ProviderMember | None) -> Membership | None:
    if member is None:
        return None
    return Membership(role=member.role, status=member.status)  # type: ignore[arg-type]


async def _profile_out(
    session: AsyncSession, provider: Provider, prefs: Preferences, member: ProviderMember | None
) -> ProviderProfile:
    fields = await _profile_fields(session, provider, prefs)
    return ProviderProfile(**fields, membership=_membership_out(member))


async def _document_kinds(session: AsyncSession, provider_id: uuid.UUID) -> frozenset[DocumentKind]:
    kinds = await session.scalars(
        select(ProviderDocument.kind).where(
            ProviderDocument.provider_id == provider_id,
            ProviderDocument.status != DocumentStatus.REJECTED,
        )
    )
    return frozenset(DocumentKind(k) for k in kinds)


async def _missing(session: AsyncSession, provider: Provider) -> list[str]:
    return missing_for_submit(
        ApplicationFacts(
            kind=ProviderKind(provider.kind),
            has_display_name=bool(provider.display_name),
            has_base_destination=provider.base_destination_id is not None,
            language_count=len(provider.languages or []),
            has_legal_name=bool(provider.legal_name),
            document_kinds=await _document_kinds(session, provider.id),
            terms_accepted=True,  # accepted in the submit call itself
        )
    )


async def _workspace_out(
    session: AsyncSession, provider: Provider, prefs: Preferences, member: ProviderMember | None
) -> ProviderWorkspace:
    fields = await _profile_fields(session, provider, prefs)
    return ProviderWorkspace(
        **fields,
        membership=_membership_out(member),
        country_code=provider.country_code,
        legal_name=provider.legal_name,
        registration_number=provider.registration_number,
        review_note=provider.review_note,
        suspended_reason=provider.suspended_reason,
        submitted_at=provider.submitted_at,
        decided_at=provider.decided_at,
        locked_fields=sorted(LOCKED_FIELDS) if provider.approved_at else [],
        terms_version=PROVIDER_TERMS_VERSION,
        terms_accepted_version=provider.terms_version,
        missing_for_submit=await _missing(session, provider),
        inquiry_count=provider.inquiry_count,
        response_count=provider.response_count,
        version=provider.version,
        created_at=provider.created_at,
    )


def _document_out(document: ProviderDocument) -> DocumentOut:
    return DocumentOut(
        id=document.id,
        kind=document.kind,  # type: ignore[arg-type]
        number=document.number,
        issuing_country=document.issuing_country,
        expires_on=document.expires_on,
        status=document.status,  # type: ignore[arg-type]
        file_available=document.media_id is not None and document.file_deleted_at is None,
        created_at=document.created_at,
        decided_at=document.decided_at,
    )


async def _members_out(session: AsyncSession, provider_id: uuid.UUID) -> list[MemberOut]:
    rows = (
        await session.scalars(
            select(ProviderMember)
            .where(ProviderMember.provider_id == provider_id)
            .order_by(ProviderMember.created_at, ProviderMember.user_id)
        )
    ).all()
    people = await profiles.authors(session, [r.user_id for r in rows])
    return [
        MemberOut(
            user=profiles.user_summary(people[r.user_id]) if r.user_id in people else None,
            role=r.role,  # type: ignore[arg-type]
            status=r.status,  # type: ignore[arg-type]
            created_at=r.created_at,
            accepted_at=r.accepted_at,
        )
        for r in rows
    ]


async def _offerings_out(
    session: AsyncSession, rows: Sequence[ProviderOffering], prefs: Preferences
) -> list[OfferingOut]:
    if not rows:
        return []
    owners = (
        await session.scalars(
            select(Provider).where(Provider.id.in_({r.provider_id for r in rows}))
        )
    ).all()
    cards = await _summaries(session, owners, prefs)
    places = await destinations.summaries_by_id(
        session, list({r.destination_id for r in rows}), prefs
    )
    covers = await media.refs(session, [r.cover_media_id for r in rows if r.cover_media_id])
    return [
        OfferingOut(
            id=r.id,
            provider=cards[r.provider_id],
            status=r.status,  # type: ignore[arg-type]
            kind=r.kind,  # type: ignore[arg-type]
            title=r.title,
            description=r.description,
            destination=places.get(r.destination_id),
            duration_minutes=r.duration_minutes,
            price_from=(
                Price(
                    amount_minor=r.price_from_minor,
                    currency=r.currency,
                    unit=r.price_unit,  # type: ignore[arg-type]
                )
                if r.price_from_minor is not None and r.currency is not None
                else None
            ),
            max_group_size=r.max_group_size,
            languages=list(r.languages or []),
            cover=covers.get(r.cover_media_id) if r.cover_media_id else None,
            published_at=r.published_at,
            created_at=r.created_at,
            updated_at=r.updated_at,
            version=r.version,
        )
        for r in rows
    ]


async def _reviews_out(session: AsyncSession, rows: Sequence[ProviderReview]) -> list[ReviewOut]:
    people = await profiles.authors(session, [r.author_id for r in rows if r.author_id])
    return [
        ReviewOut(
            id=r.id,
            provider_id=r.provider_id,
            rating=r.rating,
            body=r.body,
            author=(
                profiles.user_summary(people[r.author_id])
                if r.author_id is not None and r.author_id in people
                else None
            ),
            reply=(
                ReviewReply(body=r.reply_body, replied_at=r.replied_at)
                if r.reply_body is not None and r.replied_at is not None
                else None
            ),
            created_at=r.created_at,
        )
        for r in rows
    ]


async def _inquiries_out(
    session: AsyncSession,
    rows: Sequence[ProviderInquiry],
    viewer: uuid.UUID,
    prefs: Preferences,
    now: datetime,
) -> list[InquiryOut]:
    if not rows:
        return []
    owners = (
        await session.scalars(
            select(Provider).where(Provider.id.in_({r.provider_id for r in rows}))
        )
    ).all()
    cards = await _summaries(session, owners, prefs)
    people = await profiles.authors(session, [r.traveler_id for r in rows if r.traveler_id])
    offerings = {
        o.id: o
        for o in (
            await session.scalars(
                select(ProviderOffering).where(
                    ProviderOffering.id.in_({r.offering_id for r in rows if r.offering_id})
                )
            )
        ).all()
    }
    reviews: dict[uuid.UUID, uuid.UUID] = {
        row[0]: row[1]
        for row in (
            await session.execute(
                select(ProviderReview.inquiry_id, ProviderReview.id).where(
                    ProviderReview.inquiry_id.in_([r.id for r in rows])
                )
            )
        ).all()
    }
    out: list[InquiryOut] = []
    for r in rows:
        traveler_side = r.traveler_id == viewer
        offering = offerings.get(r.offering_id) if r.offering_id else None
        review_id = reviews.get(r.id)
        out.append(
            InquiryOut(
                id=r.id,
                provider=cards[r.provider_id],
                traveler=(
                    profiles.user_summary(people[r.traveler_id])
                    if r.traveler_id is not None and r.traveler_id in people
                    else None
                ),
                offering=(
                    OfferingRef(id=offering.id, title=offering.title, kind=offering.kind)  # type: ignore[arg-type]
                    if offering is not None
                    else None
                ),
                start_date=r.start_date,
                end_date=r.end_date,
                flexible_dates=r.flexible_dates,
                party_size=r.party_size,
                message=r.message,
                status=r.status,  # type: ignore[arg-type]
                decline_reason=r.decline_reason,
                conversation_id=r.conversation_id,
                first_response_at=r.first_response_at,
                decided_at=r.decided_at,
                completed_at=r.completed_at,
                viewer_side="traveler" if traveler_side else "provider",
                can_review=(
                    traveler_side
                    and review_id is None
                    and can_review(InquiryStatus(r.status), r.completed_at, now)
                ),
                review_id=review_id,
                created_at=r.created_at,
                updated_at=r.updated_at,
                version=r.version,
            )
        )
    return out


# ───────────────────────────── shared helpers ─────────────────────────────


async def _active_member_ids(session: AsyncSession, provider_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        await session.scalars(
            select(ProviderMember.user_id).where(
                ProviderMember.provider_id == provider_id,
                ProviderMember.status == MemberStatus.ACTIVE,
            )
        )
    )


async def _managers(session: AsyncSession, provider_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        await session.scalars(
            select(ProviderMember.user_id).where(
                ProviderMember.provider_id == provider_id,
                ProviderMember.status == MemberStatus.ACTIVE,
                ProviderMember.role.in_([MemberRole.OWNER, MemberRole.MANAGER]),
            )
        )
    )


async def _owner_id(session: AsyncSession, provider_id: uuid.UUID) -> uuid.UUID | None:
    found: uuid.UUID | None = await session.scalar(
        select(ProviderMember.user_id).where(
            ProviderMember.provider_id == provider_id, ProviderMember.role == MemberRole.OWNER
        )
    )
    return found


async def _blocked(session: AsyncSession, provider_id: uuid.UUID, traveler_id: uuid.UUID) -> bool:
    return bool(
        await session.scalar(
            select(
                exists().where(
                    ProviderBlock.provider_id == provider_id,
                    ProviderBlock.traveler_id == traveler_id,
                )
            )
        )
    )


async def _notify(
    session: AsyncSession,
    recipients: Sequence[uuid.UUID],
    *,
    kind: str,
    provider: Provider,
    dedupe: str,
    actor_id: uuid.UUID | None = None,
    variant: str = "",
    entity_type: str = "provider",
    entity_id: uuid.UUID | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "provider_id": str(provider.id),
        "provider_name": provider.display_name,
        **({"variant": variant} if variant else {}),
        **(extra or {}),
    }
    for user_id in dict.fromkeys(recipients):
        await notifications.notify(
            session,
            user_id=user_id,
            kind=kind,
            actor_id=actor_id,
            entity_type=entity_type,
            entity_id=entity_id or provider.id,
            payload=payload,
            dedupe_key=f"{kind}:{dedupe}:{user_id}",
        )


async def _area_path(
    session: AsyncSession, destination_id: uuid.UUID, field: str
) -> list[uuid.UUID]:
    path = await destinations.ancestry(session, destination_id)
    if path is None:
        raise _invalid(field, "Pick a destination from the list.")
    return path


async def _set_base(session: AsyncSession, provider: Provider, destination_id: uuid.UUID) -> None:
    path = await _area_path(session, destination_id, "/base_destination_id")
    await session.execute(
        delete(ProviderServiceArea).where(
            ProviderServiceArea.provider_id == provider.id, ProviderServiceArea.is_base.is_(True)
        )
    )
    existing = await session.get(ProviderServiceArea, (provider.id, destination_id))
    if existing is not None:  # the new base town was a service area: it becomes the base
        existing.is_base = True
        existing.path = path
    else:
        session.add(
            ProviderServiceArea(
                provider_id=provider.id, destination_id=destination_id, path=path, is_base=True
            )
        )
    provider.base_destination_id = destination_id


async def _usable_picture(
    session: AsyncSession, user_id: uuid.UUID, media_id: uuid.UUID | None, field: str
) -> None:
    if media_id is not None and media_id not in await media.usable_ids(
        session, user_id, [media_id], "provider"
    ):
        raise _invalid(field, "Upload the picture first.")


def _first_response(provider: Provider, inquiry: ProviderInquiry, now: datetime) -> None:
    if inquiry.first_response_at is not None:
        return
    inquiry.first_response_at = now
    provider.response_count += 1
    provider.response_seconds_total += max(0, int((now - inquiry.created_at).total_seconds()))


def _desc_after(
    column: Any, id_column: Any, position: dict[str, Any] | None
) -> ColumnElement[bool] | None:
    if position is None:
        return None
    at = datetime.fromisoformat(str(position["at"]))
    after = uuid.UUID(str(position["id"]))
    return or_(column < at, and_(column == at, id_column < after))


@dataclass(frozen=True, slots=True)
class ChatPolicy:
    """Send rights and header of a provider chat (read by messaging, ADR-0036)."""

    restriction: str | None
    title: str | None
    avatar_media_id: uuid.UUID | None
    counterpart_id: uuid.UUID | None


# ───────────────────────────── the app service ─────────────────────────────


class ProviderService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        clock: Clock,
        cursors: CursorCodec,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._clock = clock
        self._cursors = cursors

    # ─────────────── loading ───────────────

    async def _provider(
        self, session: AsyncSession, provider_id: uuid.UUID, *, lock: bool = False
    ) -> Provider:
        provider = await session.get(Provider, provider_id, with_for_update=lock)
        if provider is None:
            raise _not_found()
        return provider

    async def _member(
        self, session: AsyncSession, provider_id: uuid.UUID, user_id: uuid.UUID
    ) -> ProviderMember | None:
        return await session.get(ProviderMember, (provider_id, user_id))

    async def _visible(
        self, session: AsyncSession, provider_id: uuid.UUID, viewer: uuid.UUID | None
    ) -> tuple[Provider, ProviderMember | None]:
        """Approved providers for everyone; others only for their own members (PROV-003)."""
        provider = await self._provider(session, provider_id)
        member = await self._member(session, provider_id, viewer) if viewer else None
        if provider.status != ProviderStatus.APPROVED and member is None:
            raise _not_found()
        if (
            provider.status == ProviderStatus.APPROVED
            and member is None
            and viewer is not None
            and await _blocked(session, provider_id, viewer)
        ):
            raise _not_found()
        return provider, member

    async def _acting(
        self,
        session: AsyncSession,
        provider_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        manage: bool,
        lock: bool = False,
    ) -> tuple[Provider, ProviderMember]:
        """An active member (``manage``: owner or manager). Outsiders get 404."""
        provider = await self._provider(session, provider_id, lock=lock)
        member = await self._member(session, provider_id, user_id)
        if member is None:
            raise _not_found()
        if member.status != MemberStatus.ACTIVE:
            raise _forbidden("Accept the invitation first.")
        if manage and not can_manage_profile(MemberRole(member.role)):
            raise _forbidden("Only the owner and managers can do that.")
        return provider, member

    @staticmethod
    def _ensure_editable(provider: Provider) -> None:
        if ProviderStatus(provider.status) not in EDITABLE_STATUSES:
            raise AppError(ErrorCode.CONFLICT, f"This profile is {provider.status}.")

    # ─────────────── public reads ───────────────

    async def list_providers(
        self,
        viewer: uuid.UUID | None,
        *,
        destination_id: uuid.UUID | None,
        kind: str | None,
        language: str | None,
        specialty: str | None,
        cursor: str | None,
        limit: int,
        prefs: Preferences,
    ) -> ProviderPage:
        score = (Provider.rating_sum + PRIOR_MEAN * PRIOR_WEIGHT) / (
            Provider.rating_count + PRIOR_WEIGHT
        )
        rate = case(
            (Provider.inquiry_count > 0, Provider.response_count * 1.0 / Provider.inquiry_count),
            else_=0.0,
        )
        query = select(Provider, score, rate).where(Provider.status == ProviderStatus.APPROVED)
        scope = f"providers.{destination_id}.{kind}.{language}.{specialty}.{viewer}"
        async with self._sessionmaker() as session:
            if destination_id is not None:
                ancestry = await destinations.ancestry(session, destination_id)
                if ancestry is None:
                    raise _not_found("Destination")
                inside = select(ProviderServiceArea.provider_id).where(
                    or_(
                        ProviderServiceArea.destination_id.in_(ancestry),
                        ProviderServiceArea.path.contains([destination_id]),
                    )
                )
                query = query.where(Provider.id.in_(inside))
            if kind:
                query = query.where(Provider.kind == kind)
            if language:
                base = language.split("-")[0]
                query = query.where(
                    func.array_to_string(Provider.languages, " ").op("~")(
                        rf"(^| ){re.escape(base)}(-[A-Z]{{2}})?( |$)"
                    )
                )
            if specialty:
                query = query.where(Provider.specialties.contains([specialty]))
            if viewer is not None:
                query = query.where(
                    ~exists().where(
                        ProviderBlock.provider_id == Provider.id,
                        ProviderBlock.traveler_id == viewer,
                    )
                )
            if cursor:
                p = self._cursors.decode(cursor, scope=scope)
                s, r = float(p["s"]), float(p["r"])
                a, i = datetime.fromisoformat(str(p["a"])), uuid.UUID(str(p["i"]))
                query = query.where(
                    or_(
                        score < s,
                        and_(
                            score == s,
                            or_(
                                rate < r,
                                and_(
                                    rate == r,
                                    or_(
                                        Provider.approved_at < a,
                                        and_(Provider.approved_at == a, Provider.id < i),
                                    ),
                                ),
                            ),
                        ),
                    )
                )
            found = (
                await session.execute(
                    query.order_by(
                        score.desc(), rate.desc(), Provider.approved_at.desc(), Provider.id.desc()
                    ).limit(limit + 1)
                )
            ).all()
            has_more = len(found) > limit
            found = found[:limit]
            cards = await _summaries(session, [row[0] for row in found], prefs)
        next_cursor = None
        if has_more and found:
            last, s, r = found[-1]
            next_cursor = self._cursors.encode(
                {
                    "s": float(s),
                    "r": float(r),
                    "a": last.approved_at.isoformat(),
                    "i": str(last.id),
                },
                scope=scope,
            )
        return ProviderPage(
            data=[cards[row[0].id] for row in found],
            page=PageInfo(next_cursor=next_cursor, has_more=has_more),
        )

    async def get_profile(
        self, viewer: uuid.UUID | None, provider_id: uuid.UUID, prefs: Preferences
    ) -> ProviderProfile:
        async with self._sessionmaker() as session:
            provider, member = await self._visible(session, provider_id, viewer)
            return await _profile_out(session, provider, prefs, member)

    async def list_offerings(
        self,
        viewer: uuid.UUID | None,
        provider_id: uuid.UUID,
        *,
        include_all: bool,
        cursor: str | None,
        limit: int,
        prefs: Preferences,
    ) -> OfferingPage:
        scope = f"provider_offerings.{provider_id}.{include_all}"
        async with self._sessionmaker() as session:
            provider, member = await self._visible(session, provider_id, viewer)
            query = select(ProviderOffering).where(ProviderOffering.provider_id == provider.id)
            show_all = include_all and member is not None and member.status == MemberStatus.ACTIVE
            if not show_all:
                query = query.where(ProviderOffering.status == OfferingStatus.PUBLISHED)
            position = self._cursors.decode(cursor, scope=scope) if cursor else None
            after = _desc_after(ProviderOffering.created_at, ProviderOffering.id, position)
            if after is not None:
                query = query.where(after)
            rows = (
                await session.scalars(
                    query.order_by(
                        ProviderOffering.created_at.desc(), ProviderOffering.id.desc()
                    ).limit(limit + 1)
                )
            ).all()
            has_more = len(rows) > limit
            rows = rows[:limit]
            data = await _offerings_out(session, rows, prefs)
        next_cursor = (
            self._cursors.encode(
                {"at": rows[-1].created_at.isoformat(), "id": str(rows[-1].id)}, scope=scope
            )
            if has_more and rows
            else None
        )
        return OfferingPage(data=data, page=PageInfo(next_cursor=next_cursor, has_more=has_more))

    async def get_offering(
        self, viewer: uuid.UUID | None, offering_id: uuid.UUID, prefs: Preferences
    ) -> OfferingOut:
        async with self._sessionmaker() as session:
            offering = await session.get(ProviderOffering, offering_id)
            if offering is None:
                raise _not_found("Offering")
            try:
                _, member = await self._visible(session, offering.provider_id, viewer)
            except AppError:
                raise _not_found("Offering") from None
            if offering.status != OfferingStatus.PUBLISHED and (
                member is None or member.status != MemberStatus.ACTIVE
            ):
                raise _not_found("Offering")
            [out] = await _offerings_out(session, [offering], prefs)
            return out

    async def list_reviews(
        self,
        viewer: uuid.UUID | None,
        provider_id: uuid.UUID,
        *,
        cursor: str | None,
        limit: int,
    ) -> ReviewPage:
        scope = f"provider_reviews.{provider_id}"
        async with self._sessionmaker() as session:
            await self._visible(session, provider_id, viewer)
            query = select(ProviderReview).where(
                ProviderReview.provider_id == provider_id,
                ProviderReview.status == ReviewStatus.VISIBLE,
            )
            position = self._cursors.decode(cursor, scope=scope) if cursor else None
            after = _desc_after(ProviderReview.created_at, ProviderReview.id, position)
            if after is not None:
                query = query.where(after)
            rows = (
                await session.scalars(
                    query.order_by(
                        ProviderReview.created_at.desc(), ProviderReview.id.desc()
                    ).limit(limit + 1)
                )
            ).all()
            has_more = len(rows) > limit
            rows = rows[:limit]
            data = await _reviews_out(session, rows)
        next_cursor = (
            self._cursors.encode(
                {"at": rows[-1].created_at.isoformat(), "id": str(rows[-1].id)}, scope=scope
            )
            if has_more and rows
            else None
        )
        return ReviewPage(data=data, page=PageInfo(next_cursor=next_cursor, has_more=has_more))

    # ─────────────── application (PROV-001..004) ───────────────

    async def my_providers(self, user_id: uuid.UUID, prefs: Preferences) -> ProviderMembershipList:
        async with self._sessionmaker() as session:
            rows = (
                await session.execute(
                    select(ProviderMember, Provider)
                    .join(Provider, Provider.id == ProviderMember.provider_id)
                    .where(
                        ProviderMember.user_id == user_id,
                        Provider.status != ProviderStatus.DEACTIVATED,
                    )
                    .order_by(ProviderMember.created_at.desc())
                )
            ).all()
            cards = await _summaries(session, [p for _, p in rows], prefs)
            inviters = await profiles.authors(
                session, [m.invited_by for m, _ in rows if m.invited_by is not None]
            )
            return ProviderMembershipList(
                data=[
                    ProviderMembershipOut(
                        provider=cards[p.id],
                        role=m.role,
                        status=m.status,
                        invited_by=(
                            profiles.user_summary(inviters[m.invited_by])
                            if m.invited_by is not None and m.invited_by in inviters
                            else None
                        ),
                        created_at=m.created_at,
                    )
                    for m, p in rows
                ]
            )

    async def create(
        self,
        principal: Principal,
        request: CreateProviderRequest,
        *,
        idempotency_key: uuid.UUID,
        prefs: Preferences,
    ) -> ProviderWorkspace:
        me = principal.user_id
        if not principal.email_verified:
            raise AppError(ErrorCode.EMAIL_UNVERIFIED, "Verify your email to apply.")
        async with self._sessionmaker() as session, session.begin():
            replay = await platform.idempotency.claim(
                session,
                user_id=me,
                key=idempotency_key,
                route=CREATE_ROUTE,
                payload=request.model_dump(mode="json"),
            )
            if replay is not None:
                return ProviderWorkspace.model_validate(replay.body)
            if request.kind == "guide" and await session.scalar(
                select(
                    exists().where(
                        ProviderMember.user_id == me,
                        ProviderMember.role == MemberRole.OWNER,
                        ProviderMember.provider_id == Provider.id,
                        Provider.kind == ProviderKind.GUIDE,
                        Provider.status.notin_(
                            [ProviderStatus.REJECTED, ProviderStatus.DEACTIVATED]
                        ),
                    )
                )
            ):
                raise AppError(ErrorCode.GUIDE_PROFILE_EXISTS, "You already have a guide profile.")
            await _usable_picture(session, me, request.logo_media_id, "/logo_media_id")
            await _usable_picture(session, me, request.cover_media_id, "/cover_media_id")
            slug = _slugify(request.display_name)
            for _ in range(5):
                candidate = f"{slug}-{secrets.token_hex(3)}"
                if not await session.scalar(select(exists().where(Provider.slug == candidate))):
                    slug = candidate
                    break
            provider = Provider(
                kind=request.kind,
                slug=slug,
                display_name=request.display_name,
                legal_name=request.legal_name,
                tagline=request.tagline or None,
                about=request.about or None,
                country_code=request.country_code,
                base_destination_id=request.base_destination_id,
                languages=list(request.languages or []),
                specialties=list(request.specialties or []),
                years_experience=request.years_experience,
                website_url=str(request.website_url) if request.website_url else None,
                registration_number=request.registration_number,
                logo_media_id=request.logo_media_id,
                cover_media_id=request.cover_media_id,
                created_by=me,
            )
            session.add(provider)
            await session.flush()
            await _set_base(session, provider, request.base_destination_id)
            session.add(
                ProviderMember(
                    provider_id=provider.id,
                    user_id=me,
                    role=MemberRole.OWNER,
                    status=MemberStatus.ACTIVE,
                    accepted_at=self._clock.now(),
                )
            )
            await session.flush()
            await session.refresh(provider)
            member = await self._member(session, provider.id, me)
            out = await _workspace_out(session, provider, prefs, member)
            platform.record_event(
                session,
                aggregate_type="provider",
                aggregate_id=provider.id,
                event_type="provider.created",
                payload={"provider_id": str(provider.id), "kind": provider.kind},
            )
            await platform.idempotency.complete(
                session,
                user_id=me,
                key=idempotency_key,
                status=201,
                body=out.model_dump(mode="json"),
            )
            return out

    async def workspace(
        self, user_id: uuid.UUID, provider_id: uuid.UUID, prefs: Preferences
    ) -> ProviderWorkspace:
        async with self._sessionmaker() as session:
            provider, member = await self._acting(session, provider_id, user_id, manage=False)
            return await _workspace_out(session, provider, prefs, member)

    async def update(
        self,
        user_id: uuid.UUID,
        provider_id: uuid.UUID,
        request: UpdateProviderRequest,
        *,
        if_match: str | None,
        prefs: Preferences,
    ) -> ProviderWorkspace:
        changes = request.model_dump(exclude_unset=True)
        async with self._sessionmaker() as session, session.begin():
            provider, member = await self._acting(
                session, provider_id, user_id, manage=True, lock=True
            )
            self._ensure_editable(provider)
            _check_version(provider.version, if_match)
            if provider.approved_at is not None:
                locked = sorted(
                    f for f in LOCKED_FIELDS if f in changes and changes[f] != getattr(provider, f)
                )
                if locked:
                    raise AppError(
                        ErrorCode.PROVIDER_FIELD_LOCKED,
                        "These details were verified. Contact support to change them.",
                        extensions={"fields": locked},
                    )
            if changes.get("kind") == ProviderKind.GUIDE and provider.kind != ProviderKind.GUIDE:
                raise _invalid("/kind", "Start a new guide profile instead.")
            required = ("display_name", "country_code", "base_destination_id", "kind")
            for field in required:
                if field in changes and changes[field] is None:
                    raise _invalid(f"/{field}", "This can't be empty.")
            if "logo_media_id" in changes:
                await _usable_picture(session, user_id, request.logo_media_id, "/logo_media_id")
            if "cover_media_id" in changes:
                await _usable_picture(session, user_id, request.cover_media_id, "/cover_media_id")
            if (
                request.base_destination_id is not None
                and request.base_destination_id != provider.base_destination_id
            ):
                await _set_base(session, provider, request.base_destination_id)
            for field, value in changes.items():
                if field == "base_destination_id":
                    continue
                if field == "website_url":
                    value = str(request.website_url) if request.website_url else None
                elif field in ("tagline", "about") and value == "":
                    value = None
                elif field in ("languages", "specialties"):
                    value = list(value or [])
                setattr(provider, field, value)
            provider.version += 1
            await session.flush()
            await session.refresh(provider)
            return await _workspace_out(session, provider, prefs, member)

    async def set_service_areas(
        self,
        user_id: uuid.UUID,
        provider_id: uuid.UUID,
        request: ServiceAreasRequest,
        prefs: Preferences,
    ) -> ProviderWorkspace:
        if len(request.destination_ids) > MAX_SERVICE_AREAS:
            raise AppError(
                ErrorCode.SERVICE_AREA_LIMIT, f"Pick up to {MAX_SERVICE_AREAS} service areas."
            )
        async with self._sessionmaker() as session, session.begin():
            provider, member = await self._acting(
                session, provider_id, user_id, manage=True, lock=True
            )
            self._ensure_editable(provider)
            paths = {
                d: await _area_path(session, d, f"/destination_ids/{n}")
                for n, d in enumerate(request.destination_ids)
                if d != provider.base_destination_id
            }
            await session.execute(
                delete(ProviderServiceArea).where(
                    ProviderServiceArea.provider_id == provider.id,
                    ProviderServiceArea.is_base.is_(False),
                )
            )
            for destination_id, path in paths.items():
                session.add(
                    ProviderServiceArea(
                        provider_id=provider.id, destination_id=destination_id, path=path
                    )
                )
            provider.version += 1
            await session.flush()
            await session.refresh(provider)
            return await _workspace_out(session, provider, prefs, member)

    async def list_documents(self, user_id: uuid.UUID, provider_id: uuid.UUID) -> DocumentList:
        async with self._sessionmaker() as session:
            await self._acting(session, provider_id, user_id, manage=True)
            rows = (
                await session.scalars(
                    select(ProviderDocument)
                    .where(ProviderDocument.provider_id == provider_id)
                    .order_by(ProviderDocument.created_at)
                )
            ).all()
            return DocumentList(data=[_document_out(d) for d in rows])

    async def add_document(
        self, user_id: uuid.UUID, provider_id: uuid.UUID, request: AddDocumentRequest
    ) -> DocumentOut:
        async with self._sessionmaker() as session, session.begin():
            provider, _ = await self._acting(session, provider_id, user_id, manage=True, lock=True)
            if ProviderStatus(provider.status) not in (
                ProviderStatus.DRAFT,
                ProviderStatus.CHANGES_REQUESTED,
                ProviderStatus.APPROVED,
            ):
                raise AppError(
                    ErrorCode.CONFLICT, "Documents can be added before submitting, or later."
                )
            count = await session.scalar(
                select(func.count())
                .select_from(ProviderDocument)
                .where(
                    ProviderDocument.provider_id == provider_id,
                    ProviderDocument.file_deleted_at.is_(None),
                )
            )
            if (count or 0) >= MAX_DOCUMENTS:
                raise AppError(ErrorCode.CONFLICT, f"Up to {MAX_DOCUMENTS} documents.")
            if request.media_id not in await media.usable_ids(
                session, user_id, [request.media_id], "provider_document"
            ):
                raise _invalid("/media_id", "Upload the document photo first.")
            document = ProviderDocument(
                provider_id=provider_id,
                kind=request.kind,
                media_id=request.media_id,
                number=request.number,
                issuing_country=request.issuing_country,
                expires_on=request.expires_on,
                uploaded_by=user_id,
            )
            session.add(document)
            await session.flush()
            await session.refresh(document)
            return _document_out(document)

    async def delete_document(
        self, user_id: uuid.UUID, provider_id: uuid.UUID, document_id: uuid.UUID
    ) -> None:
        async with self._sessionmaker() as session, session.begin():
            await self._acting(session, provider_id, user_id, manage=True, lock=True)
            document = await session.get(ProviderDocument, document_id)
            if document is None or document.provider_id != provider_id:
                raise _not_found("Document")
            if document.status != DocumentStatus.PENDING:
                raise AppError(ErrorCode.CONFLICT, "Checked documents stay on record.")
            if document.media_id is not None:
                await media.erase_assets(session, [document.media_id])
            await session.delete(document)

    async def submit(
        self,
        user_id: uuid.UUID,
        provider_id: uuid.UUID,
        request: SubmitProviderRequest,
        prefs: Preferences,
    ) -> ProviderWorkspace:
        now = self._clock.now()
        async with self._sessionmaker() as session, session.begin():
            provider, member = await self._acting(
                session, provider_id, user_id, manage=True, lock=True
            )
            if not can_submit(ProviderStatus(provider.status)):
                raise AppError(ErrorCode.CONFLICT, f"This profile is {provider.status}.")
            if request.terms_version != PROVIDER_TERMS_VERSION:
                raise _invalid(
                    "/terms_version", "Accept the current Provider Terms.", "outdated_version"
                )
            missing = await _missing(session, provider)
            if missing:
                raise AppError(
                    ErrorCode.PROVIDER_INCOMPLETE,
                    "A few things are still missing.",
                    extensions={"missing": missing},
                )
            provider.status = ProviderStatus.SUBMITTED
            provider.submitted_at = now
            provider.terms_version = request.terms_version
            provider.terms_accepted_at = now
            provider.version += 1
            await identity.record_consent(
                session,
                user_id,
                consent_type="provider_terms",
                version=request.terms_version,
                granted=True,
                at=now,
            )
            platform.record_event(
                session,
                aggregate_type="provider",
                aggregate_id=provider.id,
                event_type="provider.submitted",
                payload={"provider_id": str(provider.id)},
            )
            await session.flush()
            await session.refresh(provider)
            return await _workspace_out(session, provider, prefs, member)

    async def deactivate(
        self, user_id: uuid.UUID, provider_id: uuid.UUID, prefs: Preferences
    ) -> ProviderWorkspace:
        async with self._sessionmaker() as session, session.begin():
            provider, member = await self._acting(
                session, provider_id, user_id, manage=True, lock=True
            )
            if member.role != MemberRole.OWNER:
                raise _forbidden("Only the owner can close the profile.")
            if not can_deactivate(ProviderStatus(provider.status)):
                raise AppError(ErrorCode.CONFLICT, f"This profile is {provider.status}.")
            await _deactivate(session, provider, self._clock.now())
            await session.flush()
            await session.refresh(provider)
            return await _workspace_out(session, provider, prefs, member)

    # ─────────────── team (PROV-005) ───────────────

    async def list_members(self, user_id: uuid.UUID, provider_id: uuid.UUID) -> MemberList:
        async with self._sessionmaker() as session:
            await self._acting(session, provider_id, user_id, manage=False)
            return MemberList(data=await _members_out(session, provider_id))

    async def invite_member(
        self, user_id: uuid.UUID, provider_id: uuid.UUID, request: InviteMemberRequest
    ) -> MemberList:
        async with self._sessionmaker() as session, session.begin():
            provider, me = await self._acting(session, provider_id, user_id, manage=True, lock=True)
            self._ensure_editable(provider)
            if provider.kind != ProviderKind.COMPANY:
                raise _forbidden("Teams are for companies.")
            role = MemberRole(request.role)
            if not can_invite(MemberRole(me.role), role):
                raise _forbidden("Managers can invite agents only.")
            invitee = await profiles.user_id_for_handle(session, request.handle.lstrip("@"))
            if invitee is None or not await identity.active_ids(session, [invitee]):
                raise _invalid("/handle", "No traveler with that handle.")
            if await self._member(session, provider_id, invitee) is not None:
                raise AppError(ErrorCode.CONFLICT, "They're already on the team or invited.")
            session.add(
                ProviderMember(
                    provider_id=provider_id,
                    user_id=invitee,
                    role=role,
                    status=MemberStatus.INVITED,
                    invited_by=user_id,
                )
            )
            await session.flush()
            await _notify(
                session,
                [invitee],
                kind="provider_invitation",
                provider=provider,
                actor_id=user_id,
                dedupe=f"{provider_id}",
            )
            return MemberList(data=await _members_out(session, provider_id))

    async def accept_invitation(
        self, user_id: uuid.UUID, provider_id: uuid.UUID, prefs: Preferences
    ) -> ProviderWorkspace:
        async with self._sessionmaker() as session, session.begin():
            provider = await self._provider(session, provider_id, lock=True)
            member = await self._member(session, provider_id, user_id)
            if member is None:
                raise _not_found()
            self._ensure_editable(provider)
            if member.status == MemberStatus.INVITED:
                member.status = MemberStatus.ACTIVE
                member.accepted_at = self._clock.now()
                await messaging.set_provider_member(session, provider_id, user_id, active=True)
            await session.flush()
            return await _workspace_out(session, provider, prefs, member)

    async def change_role(
        self,
        user_id: uuid.UUID,
        provider_id: uuid.UUID,
        member_id: uuid.UUID,
        request: ChangeMemberRoleRequest,
    ) -> MemberList:
        async with self._sessionmaker() as session, session.begin():
            _, me = await self._acting(session, provider_id, user_id, manage=True, lock=True)
            if me.role != MemberRole.OWNER:
                raise _forbidden("Only the owner changes roles.")
            target = await self._member(session, provider_id, member_id)
            if target is None:
                raise _not_found("Member")
            if target.role == MemberRole.OWNER:
                raise _forbidden("The owner's role can't change.")
            target.role = request.role
            await session.flush()
            return MemberList(data=await _members_out(session, provider_id))

    async def remove_member(
        self, user_id: uuid.UUID, provider_id: uuid.UUID, member_id: uuid.UUID
    ) -> None:
        async with self._sessionmaker() as session, session.begin():
            await self._provider(session, provider_id, lock=True)
            me = await self._member(session, provider_id, user_id)
            target = await self._member(session, provider_id, member_id)
            if me is None or target is None:
                raise _not_found("Member")
            is_self = user_id == member_id
            if not is_self and me.status != MemberStatus.ACTIVE:
                raise _forbidden("Accept the invitation first.")
            if not can_remove(MemberRole(me.role), MemberRole(target.role), is_self=is_self):
                raise _forbidden(
                    "The owner can't leave." if is_self else "You can't remove this member."
                )
            await messaging.set_provider_member(session, provider_id, member_id, active=False)
            await session.delete(target)

    # ─────────────── offerings (PROV-006) ───────────────

    async def create_offering(
        self,
        user_id: uuid.UUID,
        provider_id: uuid.UUID,
        request: CreateOfferingRequest,
        prefs: Preferences,
    ) -> OfferingOut:
        async with self._sessionmaker() as session, session.begin():
            provider, _ = await self._acting(session, provider_id, user_id, manage=True)
            self._ensure_editable(provider)
            if not await destinations.is_active(session, request.destination_id):
                raise _invalid("/destination_id", "Pick a destination from the list.")
            await _usable_picture(session, user_id, request.cover_media_id, "/cover_media_id")
            offering = ProviderOffering(
                provider_id=provider_id,
                kind=request.kind,
                title=request.title,
                description=request.description or None,
                destination_id=request.destination_id,
                duration_minutes=request.duration_minutes,
                price_from_minor=request.price_from_minor,
                currency=request.currency,
                price_unit=request.price_unit,
                max_group_size=request.max_group_size,
                languages=list(request.languages or provider.languages or []),
                cover_media_id=request.cover_media_id,
            )
            session.add(offering)
            await session.flush()
            await session.refresh(offering)
            [out] = await _offerings_out(session, [offering], prefs)
            return out

    async def _offering_for_manager(
        self, session: AsyncSession, user_id: uuid.UUID, offering_id: uuid.UUID
    ) -> tuple[Provider, ProviderOffering]:
        offering = await session.get(ProviderOffering, offering_id, with_for_update=True)
        if offering is None:
            raise _not_found("Offering")
        try:
            provider, _ = await self._acting(session, offering.provider_id, user_id, manage=True)
        except AppError as error:
            if error.code == ErrorCode.NOT_FOUND:
                raise _not_found("Offering") from None
            raise
        if offering.status == OfferingStatus.REMOVED:
            raise AppError(ErrorCode.CONFLICT, "Our team removed this offering.")
        return provider, offering

    async def update_offering(
        self,
        user_id: uuid.UUID,
        offering_id: uuid.UUID,
        request: UpdateOfferingRequest,
        *,
        if_match: str | None,
        prefs: Preferences,
    ) -> OfferingOut:
        changes = request.model_dump(exclude_unset=True)
        async with self._sessionmaker() as session, session.begin():
            provider, offering = await self._offering_for_manager(session, user_id, offering_id)
            self._ensure_editable(provider)
            _check_version(offering.version, if_match)
            for field in ("kind", "title", "destination_id"):
                if field in changes and changes[field] is None:
                    raise _invalid(f"/{field}", "This can't be empty.")
            if request.destination_id is not None and not await destinations.is_active(
                session, request.destination_id
            ):
                raise _invalid("/destination_id", "Pick a destination from the list.")
            if "cover_media_id" in changes:
                await _usable_picture(session, user_id, request.cover_media_id, "/cover_media_id")
            for field, value in changes.items():
                if field == "languages":
                    value = list(value or [])
                elif field == "description" and value == "":
                    value = None
                setattr(offering, field, value)
            if (offering.price_from_minor is None) != (offering.currency is None):
                raise _invalid("/currency", "Send price_from_minor and currency together.")
            offering.version += 1
            await session.flush()
            await session.refresh(offering)
            [out] = await _offerings_out(session, [offering], prefs)
            return out

    async def publish_offering(
        self, user_id: uuid.UUID, offering_id: uuid.UUID, prefs: Preferences
    ) -> OfferingOut:
        async with self._sessionmaker() as session, session.begin():
            provider, offering = await self._offering_for_manager(session, user_id, offering_id)
            if provider.status != ProviderStatus.APPROVED:
                raise AppError(
                    ErrorCode.PROVIDER_NOT_APPROVED,
                    "Offerings go live once our team approves your profile.",
                )
            if offering.status != OfferingStatus.PUBLISHED:
                published = await session.scalar(
                    select(func.count())
                    .select_from(ProviderOffering)
                    .where(
                        ProviderOffering.provider_id == provider.id,
                        ProviderOffering.status == OfferingStatus.PUBLISHED,
                    )
                )
                if (published or 0) >= MAX_PUBLISHED_OFFERINGS:
                    raise AppError(
                        ErrorCode.OFFERING_LIMIT_REACHED,
                        f"Up to {MAX_PUBLISHED_OFFERINGS} offerings can be live at once.",
                    )
                offering.status = OfferingStatus.PUBLISHED
                offering.published_at = self._clock.now()
                offering.version += 1
            await session.flush()
            await session.refresh(offering)
            [out] = await _offerings_out(session, [offering], prefs)
            return out

    async def archive_offering(
        self, user_id: uuid.UUID, offering_id: uuid.UUID, prefs: Preferences
    ) -> OfferingOut:
        async with self._sessionmaker() as session, session.begin():
            _, offering = await self._offering_for_manager(session, user_id, offering_id)
            if offering.status != OfferingStatus.ARCHIVED:
                offering.status = OfferingStatus.ARCHIVED
                offering.version += 1
            await session.flush()
            await session.refresh(offering)
            [out] = await _offerings_out(session, [offering], prefs)
            return out

    # ─────────────── requests (PROV-009, PROV-010) ───────────────

    async def create_inquiry(
        self,
        principal: Principal,
        provider_id: uuid.UUID,
        request: CreateInquiryRequest,
        *,
        idempotency_key: uuid.UUID,
        prefs: Preferences,
    ) -> InquiryOut:
        me, now = principal.user_id, self._clock.now()
        if not principal.email_verified:
            raise AppError(ErrorCode.EMAIL_UNVERIFIED, "Verify your email to send requests.")
        if request.start_date is not None and request.start_date < now.date():
            raise _invalid("/start_date", "Pick a date from today on.")
        async with self._sessionmaker() as session, session.begin():
            replay = await platform.idempotency.claim(
                session,
                user_id=me,
                key=idempotency_key,
                route=INQUIRY_ROUTE,
                payload={"provider_id": str(provider_id), **request.model_dump(mode="json")},
            )
            if replay is not None:
                return InquiryOut.model_validate(replay.body)
            await trust_safety_restricted(session, me)
            provider = await self._provider(session, provider_id, lock=True)
            member = await self._member(session, provider_id, me)
            if member is not None:
                raise _forbidden("You can't send a request to your own team.")
            if provider.status != ProviderStatus.APPROVED:
                raise _not_found()
            if await _blocked(session, provider_id, me):
                raise AppError(ErrorCode.PROVIDER_BLOCKED, "You can't send requests here.")
            if request.offering_id is not None:
                offering = await session.get(ProviderOffering, request.offering_id)
                if (
                    offering is None
                    or offering.provider_id != provider_id
                    or offering.status != OfferingStatus.PUBLISHED
                ):
                    raise _invalid("/offering_id", "This offering isn't available.")
            if await session.scalar(
                select(
                    exists().where(
                        ProviderInquiry.provider_id == provider_id,
                        ProviderInquiry.traveler_id == me,
                        ProviderInquiry.status == InquiryStatus.OPEN,
                    )
                )
            ):
                raise AppError(
                    ErrorCode.INQUIRY_ALREADY_OPEN,
                    "You already have an open request here. Continue in the chat.",
                )
            members = await _active_member_ids(session, provider_id)
            conversation_id = await messaging.open_provider_conversation(
                session, provider_id, me, members
            )
            inquiry = ProviderInquiry(
                provider_id=provider_id,
                traveler_id=me,
                offering_id=request.offering_id,
                start_date=request.start_date,
                end_date=request.end_date,
                flexible_dates=request.flexible_dates,
                party_size=request.party_size,
                message=request.message,
                conversation_id=conversation_id,
            )
            session.add(inquiry)
            provider.inquiry_count += 1
            await session.flush()
            await session.refresh(inquiry)
            await _notify(
                session,
                members,
                kind="provider_inquiry",
                provider=provider,
                actor_id=me,
                dedupe=str(inquiry.id),
                entity_type="provider_inquiry",
                entity_id=inquiry.id,
                extra={"inquiry_id": str(inquiry.id), "conversation_id": str(conversation_id)},
            )
            platform.record_event(
                session,
                aggregate_type="provider",
                aggregate_id=provider_id,
                event_type="provider.inquiry_created",
                payload={"provider_id": str(provider_id), "inquiry_id": str(inquiry.id)},
            )
            [out] = await _inquiries_out(session, [inquiry], me, prefs, now)
            await platform.idempotency.complete(
                session,
                user_id=me,
                key=idempotency_key,
                status=201,
                body=out.model_dump(mode="json"),
            )
            return out

    async def _inquiry_page(
        self,
        session: AsyncSession,
        query: Any,
        *,
        viewer: uuid.UUID,
        scope: str,
        cursor: str | None,
        limit: int,
        prefs: Preferences,
    ) -> InquiryPage:
        position = self._cursors.decode(cursor, scope=scope) if cursor else None
        after = _desc_after(ProviderInquiry.created_at, ProviderInquiry.id, position)
        if after is not None:
            query = query.where(after)
        rows = (
            await session.scalars(
                query.order_by(ProviderInquiry.created_at.desc(), ProviderInquiry.id.desc()).limit(
                    limit + 1
                )
            )
        ).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        data = await _inquiries_out(session, rows, viewer, prefs, self._clock.now())
        next_cursor = (
            self._cursors.encode(
                {"at": rows[-1].created_at.isoformat(), "id": str(rows[-1].id)}, scope=scope
            )
            if has_more and rows
            else None
        )
        return InquiryPage(data=data, page=PageInfo(next_cursor=next_cursor, has_more=has_more))

    async def my_inquiries(
        self,
        user_id: uuid.UUID,
        *,
        status: str | None,
        cursor: str | None,
        limit: int,
        prefs: Preferences,
    ) -> InquiryPage:
        query = select(ProviderInquiry).where(ProviderInquiry.traveler_id == user_id)
        if status:
            query = query.where(ProviderInquiry.status == status)
        async with self._sessionmaker() as session:
            return await self._inquiry_page(
                session,
                query,
                viewer=user_id,
                scope=f"inquiries.me.{user_id}.{status}",
                cursor=cursor,
                limit=limit,
                prefs=prefs,
            )

    async def provider_inquiries(
        self,
        user_id: uuid.UUID,
        provider_id: uuid.UUID,
        *,
        status: str | None,
        cursor: str | None,
        limit: int,
        prefs: Preferences,
    ) -> InquiryPage:
        query = select(ProviderInquiry).where(ProviderInquiry.provider_id == provider_id)
        if status:
            query = query.where(ProviderInquiry.status == status)
        async with self._sessionmaker() as session:
            await self._acting(session, provider_id, user_id, manage=False)
            return await self._inquiry_page(
                session,
                query,
                viewer=user_id,
                scope=f"inquiries.{provider_id}.{status}",
                cursor=cursor,
                limit=limit,
                prefs=prefs,
            )

    async def _inquiry_side(
        self, session: AsyncSession, inquiry: ProviderInquiry, user_id: uuid.UUID
    ) -> Side:
        if inquiry.traveler_id == user_id:
            return Side.TRAVELER
        member = await self._member(session, inquiry.provider_id, user_id)
        if member is not None and member.status == MemberStatus.ACTIVE:
            return Side.PROVIDER
        raise _not_found("Request")

    async def get_inquiry(
        self, user_id: uuid.UUID, inquiry_id: uuid.UUID, prefs: Preferences
    ) -> InquiryOut:
        async with self._sessionmaker() as session:
            inquiry = await session.get(ProviderInquiry, inquiry_id)
            if inquiry is None:
                raise _not_found("Request")
            await self._inquiry_side(session, inquiry, user_id)
            [out] = await _inquiries_out(session, [inquiry], user_id, prefs, self._clock.now())
            return out

    async def transition(
        self,
        user_id: uuid.UUID,
        inquiry_id: uuid.UUID,
        action: InquiryAction,
        *,
        reason: str | None = None,
        if_match: str | None = None,
        prefs: Preferences,
    ) -> InquiryOut:
        now = self._clock.now()
        async with self._sessionmaker() as session, session.begin():
            inquiry = await session.get(ProviderInquiry, inquiry_id, with_for_update=True)
            if inquiry is None:
                raise _not_found("Request")
            side = await self._inquiry_side(session, inquiry, user_id)
            _check_version(inquiry.version, if_match)
            provider = await self._provider(session, inquiry.provider_id, lock=True)
            target = inquiry_transition(InquiryStatus(inquiry.status), action, side)
            if target is None:
                raise AppError(
                    ErrorCode.INQUIRY_TRANSITION_INVALID,
                    f"This request is {inquiry.status}; you can't {action.value} it.",
                )
            if action is InquiryAction.ACCEPT and provider.status != ProviderStatus.APPROVED:
                raise AppError(ErrorCode.PROVIDER_NOT_APPROVED, "Your profile isn't live.")
            inquiry.status = target
            inquiry.version += 1
            if action in (InquiryAction.ACCEPT, InquiryAction.DECLINE):
                inquiry.decided_at = now
                _first_response(provider, inquiry, now)
            if action is InquiryAction.DECLINE:
                inquiry.decline_reason = reason or None
            if target is InquiryStatus.COMPLETED:
                inquiry.completed_at = now
            variant = {
                InquiryAction.ACCEPT: "accepted",
                InquiryAction.DECLINE: "declined",
                InquiryAction.COMPLETE: "completed",
                InquiryAction.WITHDRAW: "withdrawn",
                InquiryAction.CANCEL: (
                    "cancelled_by_traveler" if side is Side.TRAVELER else "cancelled_by_provider"
                ),
            }[action]
            if side is Side.TRAVELER:
                recipients = await _active_member_ids(session, provider.id)
            else:
                recipients = [inquiry.traveler_id] if inquiry.traveler_id else []
            await _notify(
                session,
                recipients,
                kind="provider_inquiry_update",
                provider=provider,
                actor_id=user_id,
                variant=variant,
                dedupe=f"{inquiry.id}:{variant}",
                entity_type="provider_inquiry",
                entity_id=inquiry.id,
                extra={
                    "inquiry_id": str(inquiry.id),
                    "conversation_id": str(inquiry.conversation_id),
                },
            )
            await session.flush()
            await session.refresh(inquiry)
            [out] = await _inquiries_out(session, [inquiry], user_id, prefs, now)
            return out

    # ─────────────── reviews (PROV-011) ───────────────

    async def create_review(
        self, user_id: uuid.UUID, inquiry_id: uuid.UUID, request: CreateReviewRequest
    ) -> ReviewOut:
        now = self._clock.now()
        async with self._sessionmaker() as session, session.begin():
            inquiry = await session.get(ProviderInquiry, inquiry_id, with_for_update=True)
            if inquiry is None or inquiry.traveler_id != user_id:
                raise _not_found("Request")
            if not can_review(InquiryStatus(inquiry.status), inquiry.completed_at, now):
                raise AppError(
                    ErrorCode.REVIEW_NOT_ALLOWED,
                    "You can review within 60 days after a completed request.",
                )
            if await session.scalar(
                select(exists().where(ProviderReview.inquiry_id == inquiry_id))
            ):
                raise AppError(ErrorCode.REVIEW_NOT_ALLOWED, "You already reviewed this request.")
            provider = await self._provider(session, inquiry.provider_id, lock=True)
            review = ProviderReview(
                provider_id=provider.id,
                inquiry_id=inquiry_id,
                author_id=user_id,
                rating=request.rating,
                body=(request.body or "").strip() or None,
            )
            session.add(review)
            provider.rating_count += 1
            provider.rating_sum += request.rating
            await session.flush()
            await session.refresh(review)
            await _notify(
                session,
                await _managers(session, provider.id),
                kind="provider_review",
                provider=provider,
                actor_id=user_id,
                dedupe=str(review.id),
                entity_type="provider_review",
                entity_id=review.id,
            )
            [out] = await _reviews_out(session, [review])
            return out

    async def reply_review(
        self, user_id: uuid.UUID, review_id: uuid.UUID, request: ReplyReviewRequest
    ) -> ReviewOut:
        async with self._sessionmaker() as session, session.begin():
            review = await session.get(ProviderReview, review_id, with_for_update=True)
            if review is None or review.status != ReviewStatus.VISIBLE:
                raise _not_found("Review")
            await self._acting(session, review.provider_id, user_id, manage=True)
            if review.reply_body is not None:
                raise AppError(ErrorCode.CONFLICT, "You already replied to this review.")
            review.reply_body = request.body
            review.replied_by = user_id
            review.replied_at = self._clock.now()
            await session.flush()
            await session.refresh(review)
            [out] = await _reviews_out(session, [review])
            return out

    async def delete_review(self, user_id: uuid.UUID, review_id: uuid.UUID) -> None:
        async with self._sessionmaker() as session, session.begin():
            review = await session.get(ProviderReview, review_id, with_for_update=True)
            if review is None or review.author_id != user_id:
                raise _not_found("Review")
            if review.status == ReviewStatus.VISIBLE:
                await _uncount(session, review)
            await session.delete(review)

    # ─────────────── blocks (PROV-012) ───────────────

    async def block_provider(self, user_id: uuid.UUID, provider_id: uuid.UUID) -> None:
        async with self._sessionmaker() as session, session.begin():
            await self._provider(session, provider_id)
            if await self._member(session, provider_id, user_id) is not None:
                raise _forbidden("You're on this team.")
            await _add_block(session, provider_id, user_id, Side.TRAVELER, user_id)

    async def unblock_provider(self, user_id: uuid.UUID, provider_id: uuid.UUID) -> None:
        async with self._sessionmaker() as session, session.begin():
            await _remove_block(session, provider_id, user_id, Side.TRAVELER)

    async def block_traveler(
        self, user_id: uuid.UUID, provider_id: uuid.UUID, traveler_id: uuid.UUID
    ) -> None:
        async with self._sessionmaker() as session, session.begin():
            await self._acting(session, provider_id, user_id, manage=True)
            if await self._member(session, provider_id, traveler_id) is not None:
                raise _invalid("/user_id", "Remove them from the team instead.")
            if not await identity.active_ids(session, [traveler_id]):
                raise _not_found("Traveler")
            await _add_block(session, provider_id, traveler_id, Side.PROVIDER, user_id)

    async def unblock_traveler(
        self, user_id: uuid.UUID, provider_id: uuid.UUID, traveler_id: uuid.UUID
    ) -> None:
        async with self._sessionmaker() as session, session.begin():
            await self._acting(session, provider_id, user_id, manage=True)
            await _remove_block(session, provider_id, traveler_id, Side.PROVIDER)


async def trust_safety_restricted(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Requests are messages to strangers: a messaging restriction covers them too."""
    from app.modules.trust_safety import service as trust_safety

    await trust_safety.ensure_not_restricted(
        session,
        user_id,
        "messaging_limited",
        message="Messaging is limited on your account right now.",
    )


async def _add_block(
    session: AsyncSession, provider_id: uuid.UUID, traveler_id: uuid.UUID, side: Side, by: uuid.UUID
) -> None:
    if await session.get(ProviderBlock, (provider_id, traveler_id, side)) is None:
        session.add(
            ProviderBlock(
                provider_id=provider_id, traveler_id=traveler_id, side=side, created_by=by
            )
        )
        await session.flush()


async def _remove_block(
    session: AsyncSession, provider_id: uuid.UUID, traveler_id: uuid.UUID, side: Side
) -> None:
    block = await session.get(ProviderBlock, (provider_id, traveler_id, side))
    if block is not None:
        await session.delete(block)


async def _uncount(session: AsyncSession, review: ProviderReview) -> None:
    await session.execute(
        update(Provider)
        .where(Provider.id == review.provider_id)
        .values(
            rating_count=func.greatest(Provider.rating_count - 1, 0),
            rating_sum=func.greatest(Provider.rating_sum - review.rating, 0),
        )
    )


async def _deactivate(session: AsyncSession, provider: Provider, now: datetime) -> None:
    """Close a profile for good: hidden, no new requests, open requests withdrawn."""
    provider.status = ProviderStatus.DEACTIVATED
    provider.deactivated_at = now
    provider.version += 1
    await session.execute(
        update(ProviderOffering)
        .where(
            ProviderOffering.provider_id == provider.id,
            ProviderOffering.status == OfferingStatus.PUBLISHED,
        )
        .values(status=OfferingStatus.ARCHIVED)
    )
    await session.execute(
        update(ProviderInquiry)
        .where(
            ProviderInquiry.provider_id == provider.id,
            ProviderInquiry.status.in_([InquiryStatus.OPEN, InquiryStatus.ACCEPTED]),
        )
        .values(status=InquiryStatus.CANCELLED, version=ProviderInquiry.version + 1)
    )


# ───────────────────────────── messaging (provider chats) ─────────────────────────────


async def chat_policy(
    session: AsyncSession,
    provider_id: uuid.UUID,
    traveler_id: uuid.UUID | None,
    user_id: uuid.UUID,
) -> ChatPolicy:
    """Send rights and header of a provider chat for ``user_id`` (wired into messaging)."""
    provider = await session.get(Provider, provider_id)
    if provider is None:
        return ChatPolicy("provider_unavailable", None, None, None)
    is_traveler = traveler_id is not None and traveler_id == user_id
    restriction: str | None = None
    if provider.status != ProviderStatus.APPROVED or traveler_id is None:
        restriction = "provider_unavailable"
    elif await _blocked(session, provider_id, traveler_id):
        restriction = "blocked"
    return ChatPolicy(
        restriction=restriction,
        title=provider.display_name,
        avatar_media_id=provider.logo_media_id if is_traveler else None,
        counterpart_id=None if is_traveler else traveler_id,
    )


async def record_first_response(
    session: AsyncSession, conversation_id: uuid.UUID, sender_id: uuid.UUID, now: datetime
) -> int:
    """A provider member wrote in the chat: open requests there are answered (PROV-010)."""
    rows = (
        await session.scalars(
            select(ProviderInquiry)
            .where(
                ProviderInquiry.conversation_id == conversation_id,
                ProviderInquiry.first_response_at.is_(None),
                ProviderInquiry.status.in_([InquiryStatus.OPEN, InquiryStatus.ACCEPTED]),
            )
            .with_for_update()
        )
    ).all()
    answered = 0
    for inquiry in rows:
        member = await session.get(ProviderMember, (inquiry.provider_id, sender_id))
        if member is None or member.status != MemberStatus.ACTIVE:
            continue
        provider = await session.get(Provider, inquiry.provider_id, with_for_update=True)
        if provider is None:
            continue
        _first_response(provider, inquiry, now)
        answered += 1
    return answered


# ───────────────────────────── reports and moderation ─────────────────────────────


async def provider_evidence(
    session: AsyncSession, target_id: uuid.UUID, reporter_id: uuid.UUID
) -> tuple[uuid.UUID | None, dict[str, Any]] | None:
    provider = await session.get(Provider, target_id)
    if provider is None or (
        provider.status != ProviderStatus.APPROVED
        and await session.get(ProviderMember, (target_id, reporter_id)) is None
    ):
        return None
    return await _owner_id(session, target_id), {
        "provider_id": str(provider.id),
        "kind": provider.kind,
        "display_name": provider.display_name,
        "tagline": provider.tagline,
        "about": provider.about,
        "website_url": provider.website_url,
        "logo_media_id": str(provider.logo_media_id) if provider.logo_media_id else None,
    }


async def offering_evidence(
    session: AsyncSession, target_id: uuid.UUID, reporter_id: uuid.UUID
) -> tuple[uuid.UUID | None, dict[str, Any]] | None:
    offering = await session.get(ProviderOffering, target_id)
    if offering is None or offering.status != OfferingStatus.PUBLISHED:
        return None
    return await _owner_id(session, offering.provider_id), {
        "provider_id": str(offering.provider_id),
        "offering_id": str(offering.id),
        "title": offering.title,
        "description": offering.description,
        "price_from_minor": offering.price_from_minor,
        "currency": offering.currency,
    }


async def review_evidence(
    session: AsyncSession, target_id: uuid.UUID, reporter_id: uuid.UUID
) -> tuple[uuid.UUID | None, dict[str, Any]] | None:
    review = await session.get(ProviderReview, target_id)
    if review is None or review.status != ReviewStatus.VISIBLE:
        return None
    return review.author_id, {
        "provider_id": str(review.provider_id),
        "review_id": str(review.id),
        "rating": review.rating,
        "body": review.body,
        "reply_body": review.reply_body,
    }


async def moderate_content(
    session: AsyncSession, target_type: str, target_id: uuid.UUID, *, remove: bool
) -> uuid.UUID | None:
    """Staff remove or restore an offering or a review (``remove_content``/``restore_content``).
    Returns the account to tell (provider owner or review author)."""
    if target_type == "provider_offering":
        offering = await session.get(ProviderOffering, target_id, with_for_update=True)
        if offering is None:
            raise _not_found("Offering")
        if remove:
            offering.status = OfferingStatus.REMOVED
        elif offering.status == OfferingStatus.REMOVED:
            offering.status = OfferingStatus.DRAFT
        offering.version += 1
        return await _owner_id(session, offering.provider_id)
    review = await session.get(ProviderReview, target_id, with_for_update=True)
    if review is None:
        raise _not_found("Review")
    if remove and review.status == ReviewStatus.VISIBLE:
        review.status = ReviewStatus.REMOVED
        await _uncount(session, review)
    elif not remove and review.status == ReviewStatus.REMOVED:
        review.status = ReviewStatus.VISIBLE
        await session.execute(
            update(Provider)
            .where(Provider.id == review.provider_id)
            .values(
                rating_count=Provider.rating_count + 1,
                rating_sum=Provider.rating_sum + review.rating,
            )
        )
    return review.author_id


# ───────────────────────────── staff console (PROV-013) ─────────────────────────────


async def staff_list(
    session: AsyncSession,
    cursors: CursorCodec,
    *,
    status: str | None,
    kind: str | None,
    cursor: str | None,
    limit: int,
) -> AdminProviderPage:
    """Submitted applications oldest first (the queue); other filters newest first."""
    queue = status == ProviderStatus.SUBMITTED
    scope = f"admin.providers.{status}.{kind}"
    at = func.coalesce(Provider.submitted_at, Provider.created_at)
    query = select(Provider, at)
    if status:
        query = query.where(Provider.status == status)
    if kind:
        query = query.where(Provider.kind == kind)
    if cursor:
        p = cursors.decode(cursor, scope=scope)
        when, after = datetime.fromisoformat(str(p["at"])), uuid.UUID(str(p["id"]))
        query = query.where(
            or_(at > when, and_(at == when, Provider.id > after))
            if queue
            else or_(at < when, and_(at == when, Provider.id < after))
        )
    order = (at.asc(), Provider.id.asc()) if queue else (at.desc(), Provider.id.desc())
    found = (await session.execute(query.order_by(*order).limit(limit + 1))).all()
    has_more = len(found) > limit
    found = found[:limit]
    owners: dict[uuid.UUID, uuid.UUID] = {
        row[0]: row[1]
        for row in (
            await session.execute(
                select(ProviderMember.provider_id, ProviderMember.user_id).where(
                    ProviderMember.provider_id.in_([p.id for p, _ in found]),
                    ProviderMember.role == MemberRole.OWNER,
                )
            )
        ).all()
    }
    people = await profiles.authors(session, list(owners.values()))
    data = [
        AdminProviderSummary(
            id=p.id,
            kind=p.kind,
            status=p.status,
            display_name=p.display_name,
            country_code=p.country_code,
            owner=(
                profiles.user_summary(people[owners[p.id]])
                if p.id in owners and owners[p.id] in people
                else None
            ),
            submitted_at=p.submitted_at,
            decided_at=p.decided_at,
            created_at=p.created_at,
        )
        for p, _ in found
    ]
    next_cursor = (
        cursors.encode({"at": found[-1][1].isoformat(), "id": str(found[-1][0].id)}, scope=scope)
        if has_more and found
        else None
    )
    return AdminProviderPage(data=data, page=PageInfo(next_cursor=next_cursor, has_more=has_more))


async def staff_detail(
    session: AsyncSession, provider_id: uuid.UUID, prefs: Preferences, *, open_reports: int = 0
) -> AdminProvider:
    provider = await session.get(Provider, provider_id)
    if provider is None:
        raise _not_found()
    documents = (
        await session.scalars(
            select(ProviderDocument)
            .where(ProviderDocument.provider_id == provider_id)
            .order_by(ProviderDocument.created_at)
        )
    ).all()
    owner = await _owner_id(session, provider_id)
    people = await profiles.authors(session, [owner] if owner else [])
    return AdminProvider(
        provider=await _workspace_out(session, provider, prefs, None),
        owner=profiles.user_summary(people[owner]) if owner and owner in people else None,
        members=await _members_out(session, provider_id),
        documents=[
            AdminDocument(
                **_document_out(d).model_dump(), decided_by=d.decided_by, uploaded_by=d.uploaded_by
            )
            for d in documents
        ],
        decided_by=provider.decided_by,
        open_report_count=open_reports,
    )


async def staff_document_link(
    session: AsyncSession, provider_id: uuid.UUID, document_id: uuid.UUID, sign: media.Signer | None
) -> DocumentFileLink:
    """A short-lived signed link to one verification document (PROV-004; audited by admin)."""
    document = await session.get(ProviderDocument, document_id)
    if document is None or document.provider_id != provider_id:
        raise _not_found("Document")
    if document.media_id is None or document.file_deleted_at is not None or sign is None:
        raise AppError(ErrorCode.CONFLICT, "The file is no longer kept.", status=410)
    ref = (await media.refs(session, [document.media_id], sign=sign)).get(document.media_id)
    if ref is None or ref.url is None or ref.url_expires_at is None:
        raise AppError(ErrorCode.CONFLICT, "The file is still being processed.")
    return DocumentFileLink(url=ref.url, expires_at=ref.url_expires_at)


async def staff_decide(
    session: AsyncSession,
    provider_id: uuid.UUID,
    request: ProviderDecisionRequest,
    *,
    staff_id: uuid.UUID,
    now: datetime,
) -> Provider:
    provider = await session.get(Provider, provider_id, with_for_update=True)
    if provider is None:
        raise _not_found()
    decision = Decision(request.decision)
    target = decision_target(ProviderStatus(provider.status), decision)
    if target is None:
        raise AppError(ErrorCode.CONFLICT, f"This application is {provider.status}.")
    for item in request.documents:
        document = await session.get(ProviderDocument, item.id, with_for_update=True)
        if document is None or document.provider_id != provider_id:
            raise _invalid("/documents", "A document isn't part of this application.")
        document.status = item.status
        document.decided_by = staff_id
        document.decided_at = now
    if decision is Decision.APPROVE:
        # Documents not explicitly rejected count as checked with the approval.
        await session.execute(
            update(ProviderDocument)
            .where(
                ProviderDocument.provider_id == provider_id,
                ProviderDocument.status == DocumentStatus.PENDING,
            )
            .values(status=DocumentStatus.ACCEPTED, decided_by=staff_id, decided_at=now)
        )
        provider.approved_at = provider.approved_at or now
    elif decision is Decision.REJECT:
        await session.execute(
            update(ProviderDocument)
            .where(
                ProviderDocument.provider_id == provider_id,
                ProviderDocument.decided_at.is_(None),
            )
            .values(decided_by=staff_id, decided_at=now)
        )
    provider.status = target
    provider.decided_at = now
    provider.decided_by = staff_id
    provider.review_note = (request.note or "").strip() or None
    provider.version += 1
    variant = {
        Decision.APPROVE: "approved",
        Decision.REQUEST_CHANGES: "changes_requested",
        Decision.REJECT: "rejected",
    }[decision]
    await _notify(
        session,
        await _managers(session, provider_id),
        kind="provider_application",
        provider=provider,
        variant=variant,
        dedupe=f"{provider_id}:{variant}:{now.isoformat()}",
    )
    platform.record_event(
        session,
        aggregate_type="provider",
        aggregate_id=provider_id,
        event_type=f"provider.{variant}",
        payload={"provider_id": str(provider_id)},
    )
    return provider


async def staff_suspend(
    session: AsyncSession,
    provider_id: uuid.UUID,
    *,
    suspend: bool,
    reason: str | None,
    now: datetime,
) -> Provider:
    provider = await session.get(Provider, provider_id, with_for_update=True)
    if provider is None:
        raise _not_found()
    status = ProviderStatus(provider.status)
    if suspend and not can_suspend(status):
        raise AppError(ErrorCode.CONFLICT, f"Only approved providers can be suspended ({status}).")
    if not suspend and not can_reinstate(status):
        raise AppError(ErrorCode.CONFLICT, f"This provider isn't suspended ({status}).")
    provider.status = ProviderStatus.SUSPENDED if suspend else ProviderStatus.APPROVED
    provider.suspended_reason = reason if suspend else None
    provider.version += 1
    variant = "suspended" if suspend else "reinstated"
    await _notify(
        session,
        await _managers(session, provider_id),
        kind="provider_application",
        provider=provider,
        variant=variant,
        dedupe=f"{provider_id}:{variant}:{now.isoformat()}",
    )
    return provider


# ───────────────────────────── account erasure and export ─────────────────────────────


async def hand_over_providers(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Before an account is erased (PROV-015): a company passes to its longest-serving manager,
    otherwise it closes; a guide profile closes and its public text is cleared. Requests the
    person sent are withdrawn or cancelled."""
    owned = (
        await session.scalars(
            select(Provider)
            .join(ProviderMember, ProviderMember.provider_id == Provider.id)
            .where(ProviderMember.user_id == user_id, ProviderMember.role == MemberRole.OWNER)
            .with_for_update(of=Provider)
        )
    ).all()
    for provider in owned:
        successor = None
        if provider.kind == ProviderKind.COMPANY:
            successor = await session.scalar(
                select(ProviderMember)
                .where(
                    ProviderMember.provider_id == provider.id,
                    ProviderMember.user_id != user_id,
                    ProviderMember.role == MemberRole.MANAGER,
                    ProviderMember.status == MemberStatus.ACTIVE,
                )
                .order_by(ProviderMember.accepted_at, ProviderMember.created_at)
                .limit(1)
            )
        if successor is not None:
            await session.execute(
                update(ProviderMember)
                .where(ProviderMember.provider_id == provider.id, ProviderMember.user_id == user_id)
                .values(role=MemberRole.MANAGER)
            )
            successor.role = MemberRole.OWNER
            await session.flush()
            continue
        if ProviderStatus(provider.status) not in (
            ProviderStatus.DEACTIVATED,
            ProviderStatus.REJECTED,
        ):
            await _deactivate(session, provider, await _db_now(session))
        if provider.kind == ProviderKind.GUIDE:
            pictures = [m for m in (provider.logo_media_id, provider.cover_media_id) if m]
            provider.tagline = None
            provider.about = None
            provider.website_url = None
            provider.logo_media_id = None
            provider.cover_media_id = None
            if pictures:
                await media.erase_assets(session, pictures)
    await session.execute(
        update(ProviderInquiry)
        .where(ProviderInquiry.traveler_id == user_id, ProviderInquiry.status == InquiryStatus.OPEN)
        .values(status=InquiryStatus.WITHDRAWN, version=ProviderInquiry.version + 1)
    )
    await session.execute(
        update(ProviderInquiry)
        .where(
            ProviderInquiry.traveler_id == user_id,
            ProviderInquiry.status == InquiryStatus.ACCEPTED,
        )
        .values(status=InquiryStatus.CANCELLED, version=ProviderInquiry.version + 1)
    )
    await session.flush()


async def _db_now(session: AsyncSession) -> datetime:
    value: datetime = await session.scalar(select(func.now()))  # type: ignore[assignment]
    return value


async def export_user_data(
    session: AsyncSession, user_id: uuid.UUID
) -> dict[str, list[dict[str, object]]]:
    """Personal-data export (AUTH-011, PROV-015): what this module holds about the user."""
    owned = select(ProviderMember.provider_id).where(
        ProviderMember.user_id == user_id, ProviderMember.role == MemberRole.OWNER
    )
    return {
        "provider_memberships": await platform.export_rows(
            session, ProviderMember, ProviderMember.user_id == user_id
        ),
        "providers_owned": await platform.export_rows(
            session,
            Provider,
            or_(Provider.id.in_(owned), Provider.created_by == user_id),
        ),
        "provider_documents_uploaded": await platform.export_rows(
            session, ProviderDocument, ProviderDocument.uploaded_by == user_id
        ),
        "provider_requests_sent": await platform.export_rows(
            session, ProviderInquiry, ProviderInquiry.traveler_id == user_id
        ),
        "provider_reviews_written": await platform.export_rows(
            session, ProviderReview, ProviderReview.author_id == user_id
        ),
        "provider_blocks": await platform.export_rows(
            session, ProviderBlock, ProviderBlock.traveler_id == user_id
        ),
    }


# ───────────────────────────── housekeeping (hourly) ─────────────────────────────


async def housekeeping(session: AsyncSession, now: datetime) -> int:
    """Expire stale requests, complete past ones (and invite a review), and delete verification
    files 90 days after the decision (PROV-004, PROV-010)."""
    changed = 0
    today: date = now.date()
    expired = await session.execute(
        update(ProviderInquiry)
        .where(
            ProviderInquiry.status == InquiryStatus.OPEN,
            or_(
                ProviderInquiry.created_at <= now - INQUIRY_EXPIRY,
                ProviderInquiry.start_date < today,
            ),
        )
        .values(status=InquiryStatus.EXPIRED, version=ProviderInquiry.version + 1)
        .execution_options(synchronize_session=False)
    )
    changed += int(getattr(expired, "rowcount", 0) or 0)

    service_day = func.coalesce(ProviderInquiry.end_date, ProviderInquiry.start_date)
    due = (
        await session.scalars(
            select(ProviderInquiry)
            .where(
                ProviderInquiry.status == InquiryStatus.ACCEPTED,
                or_(
                    service_day < today,
                    and_(
                        service_day.is_(None),
                        ProviderInquiry.decided_at <= now - UNDATED_COMPLETION,
                    ),
                ),
            )
            .limit(500)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for inquiry in due:
        inquiry.status = InquiryStatus.COMPLETED
        inquiry.completed_at = now
        inquiry.version += 1
        provider = await session.get(Provider, inquiry.provider_id)
        if provider is not None and inquiry.traveler_id is not None:
            await _notify(
                session,
                [inquiry.traveler_id],
                kind="provider_inquiry_update",
                provider=provider,
                variant="completed",
                dedupe=f"{inquiry.id}:completed",
                entity_type="provider_inquiry",
                entity_id=inquiry.id,
                extra={"inquiry_id": str(inquiry.id)},
            )
        changed += 1

    cutoff = now - DOCUMENT_RETENTION
    closed = select(Provider.id).where(
        Provider.status == ProviderStatus.DEACTIVATED, Provider.deactivated_at <= cutoff
    )
    files = (
        await session.scalars(
            select(ProviderDocument)
            .where(
                ProviderDocument.media_id.is_not(None),
                ProviderDocument.file_deleted_at.is_(None),
                or_(
                    ProviderDocument.decided_at <= cutoff,
                    ProviderDocument.provider_id.in_(closed),
                ),
            )
            .limit(500)
            .with_for_update(skip_locked=True)
        )
    ).all()
    if files:
        await media.erase_assets(session, [d.media_id for d in files if d.media_id is not None])
        for document in files:
            document.file_deleted_at = now
            document.media_id = None
        changed += len(files)
    await session.flush()
    return changed


def subscribe(router: platform.EventRouter) -> None:
    router.subscribe("message.sent", queue="default", kind=RESPONSE_JOB)


def make_handlers(
    sessionmaker: async_sessionmaker[AsyncSession], clock: Clock
) -> dict[str, platform.JobHandler]:
    async def first_response(job: platform.Job) -> None:
        data = job.payload.get("data") or {}
        if data.get("conversation_kind") != "provider":
            return
        try:
            conversation_id = uuid.UUID(str(data["conversation_id"]))
            sender_id = uuid.UUID(str(data["sender_id"]))
        except (KeyError, ValueError):
            return
        async with sessionmaker() as session, session.begin():
            await record_first_response(session, conversation_id, sender_id, clock.now())

    async def tidy(job: platform.Job) -> None:
        async with sessionmaker() as session, session.begin():
            changed = await housekeeping(session, clock.now())
        if changed:
            logger.info("providers_housekeeping", extra={"changed": changed})

    return {RESPONSE_JOB: first_response, HOUSEKEEPING_JOB: tidy}
