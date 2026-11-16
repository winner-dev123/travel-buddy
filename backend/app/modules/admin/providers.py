"""``/v1/admin/providers``: the verification queue for guides and travel companies (PROV-013).

Every route needs ``providers.verify`` (moderator and above). Reads of an application and every
change carry an audit justification (ADM-009); opening a verification document is audited on its
own (PROV-004).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.i18n import parse_accept_language
from app.core.pagination import CursorCodec
from app.core.security.principal import Permission
from app.core.time import Clock
from app.modules.admin.deps import Staff, staff
from app.modules.admin.service import _audit
from app.modules.media import service as media
from app.modules.providers import service as providers
from app.modules.providers.schemas import (
    AdminProvider,
    AdminProviderPage,
    DocumentFileLink,
    KindName,
    ProviderDecisionRequest,
    StatusName,
    SuspendProviderRequest,
)
from app.modules.trust_safety import service as trust_safety

router = APIRouter(prefix="/v1/admin/providers", tags=["admin"])

Cursor = Annotated[str | None, Query(max_length=1024)]
Limit = Annotated[int, Query(ge=1, le=100)]
AcceptLanguage = Annotated[str | None, Header(alias="Accept-Language", max_length=200)]
Reader = Annotated[Staff, Depends(staff(Permission.PROVIDERS_VERIFY))]
Justified = Annotated[Staff, Depends(staff(Permission.PROVIDERS_VERIFY, justified=True))]


class ProviderStaff:
    """Staff operations on providers; each runs in one transaction with its audit entry."""

    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        cursors: CursorCodec,
        clock: Clock,
        sign: media.Signer | None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._cursors = cursors
        self._clock = clock
        self._sign = sign

    async def _open_reports(self, session: AsyncSession, provider_id: uuid.UUID) -> int:
        count = await trust_safety.open_report_count(session, "provider", provider_id)
        return int(count)

    async def queue(
        self, *, status: str | None, kind: str | None, cursor: str | None, limit: int
    ) -> AdminProviderPage:
        async with self._sessionmaker() as session:
            return await providers.staff_list(
                session, self._cursors, status=status, kind=kind, cursor=cursor, limit=limit
            )

    async def detail(self, who: Staff, provider_id: uuid.UUID, prefs: list[str]) -> AdminProvider:
        async with self._sessionmaker() as session, session.begin():
            out = await providers.staff_detail(
                session,
                provider_id,
                prefs,
                open_reports=await self._open_reports(session, provider_id),
            )
            _audit(session, who, "provider.viewed", "provider", provider_id)
            return out

    async def document(
        self, who: Staff, provider_id: uuid.UUID, document_id: uuid.UUID
    ) -> DocumentFileLink:
        async with self._sessionmaker() as session, session.begin():
            link = await providers.staff_document_link(
                session, provider_id, document_id, self._sign
            )
            _audit(
                session,
                who,
                "provider.document_opened",
                "provider",
                provider_id,
                document_id=str(document_id),
            )
            return link

    async def decide(
        self, who: Staff, provider_id: uuid.UUID, body: ProviderDecisionRequest, prefs: list[str]
    ) -> AdminProvider:
        async with self._sessionmaker() as session, session.begin():
            await providers.staff_decide(
                session,
                provider_id,
                body,
                staff_id=who.principal.user_id,
                now=self._clock.now(),
            )
            _audit(
                session,
                who,
                f"provider.{body.decision}",
                "provider",
                provider_id,
                note=body.note,
                documents=[d.model_dump(mode="json") for d in body.documents],
            )
            await session.flush()
            return await providers.staff_detail(
                session,
                provider_id,
                prefs,
                open_reports=await self._open_reports(session, provider_id),
            )

    async def suspend(
        self,
        who: Staff,
        provider_id: uuid.UUID,
        *,
        suspend: bool,
        reason: str | None,
        prefs: list[str],
    ) -> AdminProvider:
        async with self._sessionmaker() as session, session.begin():
            await providers.staff_suspend(
                session, provider_id, suspend=suspend, reason=reason, now=self._clock.now()
            )
            _audit(
                session,
                who,
                "provider.suspended" if suspend else "provider.reinstated",
                "provider",
                provider_id,
                reason=reason,
            )
            await session.flush()
            return await providers.staff_detail(
                session,
                provider_id,
                prefs,
                open_reports=await self._open_reports(session, provider_id),
            )


def _staff_service(request: Request) -> ProviderStaff:
    service: ProviderStaff = request.app.state.provider_staff
    return service


def _no_store(model: AdminProvider | DocumentFileLink) -> JSONResponse:
    return JSONResponse(model.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


@router.get("", response_model=AdminProviderPage)
async def admin_list_providers(
    request: Request,
    who: Reader,
    status_filter: Annotated[StatusName | None, Query(alias="status")] = None,
    kind: KindName | None = None,
    cursor: Cursor = None,
    limit: Limit = 20,
) -> AdminProviderPage:
    return await _staff_service(request).queue(
        status=status_filter, kind=kind, cursor=cursor, limit=limit
    )


@router.get("/{provider_id}", response_model=AdminProvider)
async def admin_get_provider(
    provider_id: uuid.UUID, request: Request, who: Justified, accept_language: AcceptLanguage = None
) -> JSONResponse:
    return _no_store(
        await _staff_service(request).detail(
            who, provider_id, parse_accept_language(accept_language)
        )
    )


@router.get("/{provider_id}/documents/{document_id}/file", response_model=DocumentFileLink)
async def admin_document_file(
    provider_id: uuid.UUID, document_id: uuid.UUID, request: Request, who: Justified
) -> JSONResponse:
    return _no_store(await _staff_service(request).document(who, provider_id, document_id))


@router.post("/{provider_id}/decision", response_model=AdminProvider)
async def admin_decide_provider(
    provider_id: uuid.UUID,
    body: ProviderDecisionRequest,
    request: Request,
    who: Justified,
    accept_language: AcceptLanguage = None,
) -> JSONResponse:
    return _no_store(
        await _staff_service(request).decide(
            who, provider_id, body, parse_accept_language(accept_language)
        )
    )


@router.post("/{provider_id}/suspend", response_model=AdminProvider)
async def admin_suspend_provider(
    provider_id: uuid.UUID,
    body: SuspendProviderRequest,
    request: Request,
    who: Justified,
    accept_language: AcceptLanguage = None,
) -> JSONResponse:
    return _no_store(
        await _staff_service(request).suspend(
            who,
            provider_id,
            suspend=True,
            reason=body.reason,
            prefs=parse_accept_language(accept_language),
        )
    )


@router.post("/{provider_id}/reinstate", response_model=AdminProvider)
async def admin_reinstate_provider(
    provider_id: uuid.UUID, request: Request, who: Justified, accept_language: AcceptLanguage = None
) -> JSONResponse:
    return _no_store(
        await _staff_service(request).suspend(
            who,
            provider_id,
            suspend=False,
            reason=None,
            prefs=parse_accept_language(accept_language),
        )
    )
