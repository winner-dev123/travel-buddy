"""Personal-data exports (BL-6.03; AUTH-011, SAFE-010).

* ``POST /v1/users/me/data-exports`` records an ``export`` request (idempotent; one active at a
  time, enforced by a partial unique index) and queues the job.
* The job asks every module for what it holds about the user (exporters injected by the
  composition root, so identity needs no upward imports), writes a ZIP of JSON files to private
  storage and tells the user. Secrets never enter the archive (``platform.export_rows``).
* ``GET /v1/users/me/data-requests`` lists exports and deletions; a finished export carries a
  7-day link ``/v1/data-exports/{token}`` (HMAC token, no bearer needed), which re-checks the
  request and redirects to a short-lived storage URL. Expired archives are deleted daily.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import io
import json
import uuid
import zipfile
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import literal, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode
from app.core.pagination import CursorCodec, PageInfo
from app.core.time import Clock
from app.modules.identity.models import (
    DataSubjectRequest,
    DataSubjectRequestKind,
    DataSubjectRequestStatus,
)
from app.modules.identity.schemas import (
    DataSubjectRequestOut,
    DataSubjectRequestPage,
    ExportDownload,
)
from app.modules.media import service as media
from app.modules.platform import service as platform

EXPORT_ROUTE = "POST /v1/users/me/data-exports"
EXPORT_JOB = "identity.data_export"
CLEANUP_JOB = "identity.data_export_cleanup"
READY_EVENT = "identity.data_export_ready"
LINK_TTL = timedelta(days=7)
ACTIVE = (DataSubjectRequestStatus.RECEIVED, DataSubjectRequestStatus.PROCESSING)

Sections = Mapping[str, Sequence[Mapping[str, object]]]
Exporter = Callable[[AsyncSession, uuid.UUID], Awaitable[Sections]]

README = """\
Travel Buddy: your data
=======================

This archive holds the personal data Travel Buddy keeps about your account, one JSON file per
kind of record (for example posts.json, messages_sent.json, trips.json). manifest.json lists
every file and how many records it holds.

Left out on purpose: other people's personal data (for example messages they sent you), security
secrets (password and token hashes, encryption keys, reward codes) and moderation case details
that would identify the people who handle reports. Photos and videos you uploaded are listed in
media.json; download them from the app while your account is active.

Questions about your data: privacy@travelbuddy.app
"""


class ExportTokens:
    """``<payload>.<mac>`` (base64url): request id and expiry, HMAC-SHA256 under its own key."""

    def __init__(self, secret: bytes) -> None:
        self._secret = hashlib.sha256(b"data-exports\x00" + secret).digest()

    def _mac(self, payload: bytes) -> str:
        digest = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    def issue(self, request_id: uuid.UUID, expires_at: datetime) -> str:
        payload = json.dumps(
            {"r": str(request_id), "e": int(expires_at.timestamp())}, separators=(",", ":")
        ).encode()
        body = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        return f"{body}.{self._mac(payload)}"

    def read(self, token: str, *, now: datetime) -> uuid.UUID | None:
        body, _, mac = token.partition(".")
        try:
            payload = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        except (binascii.Error, ValueError):
            return None
        if not mac or not hmac.compare_digest(mac, self._mac(payload)):
            return None
        try:
            claims = json.loads(payload)
            expires = datetime.fromtimestamp(int(claims["e"]), tz=UTC)
            request_id = uuid.UUID(claims["r"])
        except (ValueError, KeyError, TypeError):
            return None
        return request_id if expires > now else None


def build_archive(sections: Sections, *, user_id: uuid.UUID, generated_at: datetime) -> bytes:
    """A ZIP with README.txt, manifest.json and one JSON file per section."""
    buffer = io.BytesIO()
    names = sorted(sections)
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", README)
        manifest = {
            "user_id": str(user_id),
            "generated_at": generated_at.isoformat(),
            "files": {f"{name}.json": len(sections[name]) for name in names},
        }
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        for name in names:
            archive.writestr(
                f"{name}.json",
                json.dumps(list(sections[name]), indent=2, ensure_ascii=False, default=str),
            )
    return buffer.getvalue()


def _out(
    record: DataSubjectRequest, *, now: datetime, tokens: ExportTokens, download_base: str | None
) -> DataSubjectRequestOut:
    download = None
    if (
        download_base is not None
        and record.kind == DataSubjectRequestKind.EXPORT
        and record.status == DataSubjectRequestStatus.COMPLETED
        and record.artifact_key
        and record.expires_at is not None
        and record.expires_at > now
    ):
        token = tokens.issue(record.id, record.expires_at)
        download = ExportDownload(url=f"{download_base}/{token}", expires_at=record.expires_at)
    return DataSubjectRequestOut(
        id=record.id,
        kind=record.kind,  # type: ignore[arg-type]
        status=record.status,  # type: ignore[arg-type]
        requested_at=record.requested_at,
        completed_at=record.completed_at,
        scheduled_for=record.scheduled_for,
        download=download,
    )


class DataExportService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        clock: Clock,
        cursors: CursorCodec,
        tokens: ExportTokens,
        storage: media.ObjectStorage | None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._clock = clock
        self._cursors = cursors
        self._tokens = tokens
        self._storage = storage

    async def request(
        self, user_id: uuid.UUID, *, idempotency_key: uuid.UUID
    ) -> tuple[DataSubjectRequestOut, bool]:
        """Returns ``(request, replayed)``; ``conflict`` while another export is under way."""
        now = self._clock.now()
        try:
            async with self._sessionmaker() as session, session.begin():
                replay = await platform.idempotency.claim(
                    session, user_id=user_id, key=idempotency_key, route=EXPORT_ROUTE, payload={}
                )
                if replay is not None:
                    return DataSubjectRequestOut.model_validate(replay.body), True
                active = await session.scalar(
                    select(DataSubjectRequest.id).where(
                        DataSubjectRequest.user_id == user_id,
                        DataSubjectRequest.kind == DataSubjectRequestKind.EXPORT,
                        DataSubjectRequest.status.in_(ACTIVE),
                    )
                )
                if active is not None:
                    raise _busy()
                record = DataSubjectRequest(
                    user_id=user_id,
                    kind=DataSubjectRequestKind.EXPORT,
                    status=DataSubjectRequestStatus.RECEIVED,
                    requested_at=now,
                )
                session.add(record)
                await session.flush()
                await platform.enqueue(
                    session,
                    queue="default",
                    kind=EXPORT_JOB,
                    payload={"request_id": str(record.id)},
                    dedupe_key=f"{EXPORT_JOB}:{record.id}",
                )
                out = _out(record, now=now, tokens=self._tokens, download_base=None)
                await platform.idempotency.complete(
                    session,
                    user_id=user_id,
                    key=idempotency_key,
                    status=202,
                    body=out.model_dump(mode="json"),
                )
                return out, False
        except IntegrityError as exc:  # a concurrent request won the partial unique index
            raise _busy() from exc

    async def list_requests(
        self, user_id: uuid.UUID, *, cursor: str | None, limit: int, download_base: str
    ) -> DataSubjectRequestPage:
        now = self._clock.now()
        async with self._sessionmaker() as session:
            conditions: list[Any] = [DataSubjectRequest.user_id == user_id]
            if cursor is not None:
                decoded = self._cursors.decode(cursor, scope="data-requests")
                conditions.append(
                    tuple_(DataSubjectRequest.requested_at, DataSubjectRequest.id)
                    < tuple_(
                        literal(datetime.fromisoformat(decoded["t"])),
                        literal(uuid.UUID(decoded["i"])),
                    )
                )
            rows = list(
                (
                    await session.scalars(
                        select(DataSubjectRequest)
                        .where(*conditions)
                        .order_by(
                            DataSubjectRequest.requested_at.desc(), DataSubjectRequest.id.desc()
                        )
                        .limit(limit + 1)
                    )
                ).all()
            )
        more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            self._cursors.encode(
                {"t": rows[-1].requested_at.isoformat(), "i": str(rows[-1].id)},
                scope="data-requests",
            )
            if more and rows
            else None
        )
        return DataSubjectRequestPage(
            data=[_out(r, now=now, tokens=self._tokens, download_base=download_base) for r in rows],
            page=PageInfo(next_cursor=next_cursor),
        )

    async def download_url(self, token: str) -> str:
        """Where a valid export link leads: a short-lived storage URL for the archive."""
        now = self._clock.now()
        request_id = self._tokens.read(token, now=now)
        if request_id is None:
            raise AppError(ErrorCode.NOT_FOUND, "This link has expired. Request a new export.")
        async with self._sessionmaker() as session:
            record = await session.get(DataSubjectRequest, request_id)
        if (
            record is None
            or record.status != DataSubjectRequestStatus.COMPLETED
            or not record.artifact_key
            or record.expires_at is None
            or record.expires_at <= now
        ):
            raise AppError(ErrorCode.NOT_FOUND, "This link has expired. Request a new export.")
        if self._storage is None:
            raise AppError(ErrorCode.SERVICE_UNAVAILABLE, "Downloads are unavailable right now.")
        url, _ = self._storage.presign_get(record.artifact_key)
        return url


def _busy() -> AppError:
    return AppError(ErrorCode.CONFLICT, "Your data is already being prepared. Check back soon.")


async def run_export(
    sessionmaker: async_sessionmaker[AsyncSession],
    clock: Clock,
    storage: media.ObjectStorage | None,
    exporters: Sequence[Exporter],
    request_id: uuid.UUID,
) -> str | None:
    """Collect, zip, store and announce one export; returns the new status (or None)."""
    async with sessionmaker() as session, session.begin():
        record = await session.get(DataSubjectRequest, request_id, with_for_update=True)
        if record is None or record.status not in ACTIVE:
            return None
        if storage is None:
            record.status = DataSubjectRequestStatus.REJECTED
            record.reason = "storage_unavailable"
            record.completed_at = clock.now()
            return record.status
        record.status = DataSubjectRequestStatus.PROCESSING
        user_id = record.user_id
    sections: dict[str, Sequence[Mapping[str, object]]] = {}
    async with sessionmaker() as session:
        for exporter in exporters:
            sections.update(await exporter(session, user_id))
    now = clock.now()
    key = f"exports/{user_id}/{request_id}.zip"
    await storage.write_private(
        key, build_archive(sections, user_id=user_id, generated_at=now), "application/zip"
    )
    async with sessionmaker() as session, session.begin():
        record = await session.get(DataSubjectRequest, request_id, with_for_update=True)
        if record is None:
            return None
        record.status = DataSubjectRequestStatus.COMPLETED
        record.completed_at = now
        record.artifact_key = key
        record.expires_at = now + LINK_TTL
        platform.record_event(
            session,
            aggregate_type="user",
            aggregate_id=user_id,
            event_type=READY_EVENT,
            payload={
                "user_id": str(user_id),
                "request_id": str(request_id),
                "expires_at": record.expires_at.isoformat(),
            },
        )
        return record.status


async def cleanup_exports(
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: media.ObjectStorage | None,
    now: datetime,
) -> int:
    """Delete archives whose link expired (retention: 7 days)."""
    async with sessionmaker() as session, session.begin():
        expired = list(
            (
                await session.scalars(
                    select(DataSubjectRequest)
                    .where(
                        DataSubjectRequest.artifact_key.is_not(None),
                        DataSubjectRequest.expires_at <= now,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(200)
                )
            ).all()
        )
        for record in expired:
            if storage is not None and record.artifact_key:
                await storage.delete_private(record.artifact_key)
            record.artifact_key = None
        return len(expired)


def make_export_handlers(
    sessionmaker: async_sessionmaker[AsyncSession],
    clock: Clock,
    storage: media.ObjectStorage | None,
    exporters: Sequence[Exporter],
) -> dict[str, platform.JobHandler]:
    async def export(job: platform.Job) -> None:
        await run_export(
            sessionmaker, clock, storage, exporters, uuid.UUID(str(job.payload["request_id"]))
        )

    async def cleanup(job: platform.Job) -> None:
        await cleanup_exports(sessionmaker, storage, clock.now())

    return {EXPORT_JOB: export, CLEANUP_JOB: cleanup}
