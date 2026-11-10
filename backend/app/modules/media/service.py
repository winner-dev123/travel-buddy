"""Media uploads (BL-1.08, POST-004, SAFE-004, docs/02 §11, docs/05 §7).

1. ``create_upload`` validates purpose, type and size, records the asset (``pending_upload``) and
   returns a 5-minute presigned PUT to the quarantine bucket.
2. ``finalize`` checks the object arrived and queues processing (``scanning``).
3. The ``media.process`` job verifies size, SHA-256 and magic bytes, runs the malware scanner,
   re-encodes to metadata-free WebP variants in the public bucket and marks the asset ``ready``,
   or ``rejected`` with a reason. Quarantine objects are deleted either way.

Video and HEIC are accepted by the contract but not processed yet (415 until the transcoding
service lands); rejected media never becomes reachable.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode
from app.core.ids import uuid7
from app.core.security.principal import Principal
from app.modules.media.config import MediaSettings as MediaSettings  # re-export for other modules
from app.modules.media.models import MediaAsset, MediaPurpose, MediaStatus, RejectionReason
from app.modules.media.processing import RejectedMediaError, process_image, verify
from app.modules.media.schemas import (
    CreateMediaUploadRequest,
    MediaAssetOut,
    MediaRef,
    MediaUpload,
    UploadTarget,
)
from app.modules.media.storage import ObjectStorage as ObjectStorage  # re-export for other modules
from app.modules.media.storage import ObjectTooLargeError
from app.modules.platform import service as platform

logger = logging.getLogger(__name__)

PROCESS_JOB = "media.process"
DELETE_OBJECTS_JOB = "media.delete_objects"
UPLOAD_ROUTE = "POST /v1/media/uploads"
MB = 1024 * 1024
IMAGES = frozenset({"image/jpeg", "image/png", "image/webp", "image/heic"})
STILL_IMAGES = frozenset({"image/jpeg", "image/png", "image/webp"})
VIDEOS = frozenset({"video/mp4", "video/quicktime"})

# docs/05 §7: purpose → (allowed types, max image bytes, max video bytes)
LIMITS: Mapping[str, tuple[frozenset[str], int, int]] = {
    MediaPurpose.POST: (IMAGES | VIDEOS, 25 * MB, 200 * MB),
    MediaPurpose.AVATAR: (IMAGES, 10 * MB, 0),
    MediaPurpose.MESSAGE: (IMAGES, 25 * MB, 0),
    MediaPurpose.GROUP_COVER: (STILL_IMAGES, 10 * MB, 0),
    MediaPurpose.CHALLENGE: (STILL_IMAGES, 10 * MB, 0),
}
PROCESSABLE = STILL_IMAGES  # HEIC needs a decoder, video a transcoding service


class MalwareScanner(Protocol):
    async def scan(self, data: bytes) -> bool:
        """True when the content is clean."""
        ...


class NoopScanner:
    """Development stand-in. SAFE-004 requires a real scanner (and CSAM hash matching) before
    launch: tracked in the backlog."""

    async def scan(self, data: bytes) -> bool:
        return True


# Mints a short-lived URL for a private object: (url, expires_at). Supplied by the composition
# root from the storage adapter; only call it after authorizing the viewer.
Signer = Callable[[str], tuple[str, datetime]]

# Purposes whose processed variants are private and served through signed URLs (BL-3.05, DM-002).
PRIVATE_PURPOSES = frozenset({MediaPurpose.MESSAGE})


def private_signer(storage: ObjectStorage | None) -> Signer | None:
    return storage.presign_get if storage is not None else None


def _keys(assets: Sequence[MediaAsset]) -> tuple[list[str], list[str]]:
    """Stored variant keys split into (public, private)."""
    public = [str(v["key"]) for a in assets for v in (a.variants or []) if not v.get("private")]
    private = [str(v["key"]) for a in assets for v in (a.variants or []) if v.get("private")]
    return public, private


def _ref(asset: MediaAsset, sign: Signer | None = None) -> MediaRef:
    variants = asset.variants or []
    ready = asset.status == MediaStatus.READY and bool(variants)
    largest = variants[0] if variants else None
    url: str | None = None
    expires_at: datetime | None = None
    if ready and largest:
        if largest.get("private"):
            if sign is not None:
                url, expires_at = sign(str(largest["key"]))
        else:
            url = str(largest["url"])
    return MediaRef(
        id=asset.id,
        kind=(
            "audio"
            if asset.mime_type.startswith("audio/")
            else "video"
            if asset.mime_type in VIDEOS
            else "image"
        ),
        status="ready"
        if ready
        else "processing"
        if asset.status in (MediaStatus.PENDING_UPLOAD, MediaStatus.SCANNING)
        else "unavailable",
        url=url,
        url_expires_at=expires_at,
        width=int(largest["width"]) if ready and largest and "width" in largest else None,
        height=int(largest["height"]) if ready and largest and "height" in largest else None,
        duration_ms=asset.duration_ms,
        alt_text=asset.alt_text,
    )


def _out(asset: MediaAsset, sign: Signer | None = None) -> MediaAssetOut:
    return MediaAssetOut.model_validate(
        {
            "id": asset.id,
            "purpose": asset.purpose,
            "status": asset.status,
            "mime_type": asset.mime_type,
            "bytes": asset.bytes,
            "width": asset.width,
            "height": asset.height,
            "duration_ms": asset.duration_ms,
            "rejection_reason": asset.rejection_reason,
            "ref": _ref(asset, sign) if asset.status != MediaStatus.DELETED else None,
            "created_at": asset.created_at,
        }
    )


class MediaService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        storage: ObjectStorage | None,
        max_pending: int = 20,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._storage = storage
        self._max_pending = max_pending

    def _store(self) -> ObjectStorage:
        if self._storage is None:
            raise AppError(ErrorCode.SERVICE_UNAVAILABLE, "Uploads are not available yet.")
        return self._storage

    async def create_upload(
        self, principal: Principal, request: CreateMediaUploadRequest, *, idempotency_key: uuid.UUID
    ) -> tuple[MediaUpload, bool]:
        storage = self._store()
        if not principal.email_verified:
            raise AppError(ErrorCode.EMAIL_UNVERIFIED, "Verify your email to upload media.")
        allowed, image_max, video_max = LIMITS[request.purpose]
        if request.mime_type not in allowed:
            raise AppError(
                ErrorCode.UNSUPPORTED_MEDIA_TYPE,
                f"{request.mime_type} is not accepted for {request.purpose} media.",
            )
        if request.mime_type not in PROCESSABLE:
            raise AppError(
                ErrorCode.UNSUPPORTED_MEDIA_TYPE,
                "Only JPEG, PNG and WebP images can be uploaded for now.",
            )
        max_bytes = video_max if request.mime_type in VIDEOS else image_max
        if request.bytes > max_bytes:
            raise AppError(
                ErrorCode.PAYLOAD_TOO_LARGE,
                f"Files for this purpose can be up to {max_bytes} bytes.",
            )
        async with self._sessionmaker() as session, session.begin():
            replay = await platform.idempotency.claim(
                session,
                user_id=principal.user_id,
                key=idempotency_key,
                route=UPLOAD_ROUTE,
                payload=request.model_dump(mode="json"),
            )
            if replay is not None:
                return MediaUpload.model_validate(replay.body), True
            pending = await session.scalar(
                select(func.count())
                .select_from(MediaAsset)
                .where(
                    MediaAsset.owner_id == principal.user_id,
                    MediaAsset.status == MediaStatus.PENDING_UPLOAD,
                    MediaAsset.created_at > func.now() - timedelta(hours=1),
                )
            )
            if (pending or 0) >= self._max_pending:
                raise AppError(
                    ErrorCode.CONFLICT, "Too many unfinished uploads. Finish or wait for them."
                )
            media_id = uuid7()
            key = f"{principal.user_id}/{media_id}"
            asset = MediaAsset(
                id=media_id,
                owner_id=principal.user_id,
                purpose=request.purpose,
                status=MediaStatus.PENDING_UPLOAD,
                mime_type=request.mime_type,
                bytes=request.bytes,
                sha256=request.sha256,
                width=request.width,
                height=request.height,
                duration_ms=request.duration_ms,
                alt_text=request.alt_text,
                quarantine_key=key,
            )
            session.add(asset)
            target = storage.presign_put(
                key, content_type=request.mime_type, content_length=request.bytes
            )
            out = MediaUpload(
                media_id=media_id,
                upload=UploadTarget(
                    url=target.url, headers=target.headers, expires_at=target.expires_at
                ),
                max_bytes=max_bytes,
            )
            await platform.idempotency.complete(
                session,
                user_id=principal.user_id,
                key=idempotency_key,
                status=201,
                body=out.model_dump(mode="json"),
            )
        return out, False

    async def get(self, owner_id: uuid.UUID, media_id: uuid.UUID) -> MediaAssetOut:
        async with self._sessionmaker() as session:
            asset = await session.get(MediaAsset, media_id)
            if asset is None or asset.owner_id != owner_id:
                raise AppError(ErrorCode.NOT_FOUND, "Media not found.")
            return _out(asset, private_signer(self._storage))

    async def finalize(self, owner_id: uuid.UUID, media_id: uuid.UUID) -> MediaAssetOut:
        storage = self._store()
        async with self._sessionmaker() as session, session.begin():
            asset = await session.get(MediaAsset, media_id, with_for_update=True)
            if asset is None or asset.owner_id != owner_id:
                raise AppError(ErrorCode.NOT_FOUND, "Media not found.")
            if asset.status in (MediaStatus.SCANNING, MediaStatus.READY):
                return _out(asset)  # finalizing again is harmless
            if asset.status != MediaStatus.PENDING_UPLOAD:
                raise AppError(ErrorCode.CONFLICT, f"This media is {asset.status}.")
            if await storage.quarantine_size(asset.quarantine_key) is None:
                raise AppError(ErrorCode.CONFLICT, "Upload the file before finalizing it.")
            asset.status = MediaStatus.SCANNING
            asset.finalized_at = func.now()
            await platform.enqueue(
                session,
                queue="default",
                kind=PROCESS_JOB,
                payload={"media_id": str(media_id)},
                dedupe_key=f"media:{media_id}",
            )
            await session.flush()
            await session.refresh(asset)
            return _out(asset)


async def process(
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: ObjectStorage,
    scanner: MalwareScanner,
    media_id: uuid.UUID,
) -> str:
    """Verify, scan and re-encode one asset; returns its final status."""
    async with sessionmaker() as session:
        asset = await session.get(MediaAsset, media_id)
        if asset is None or asset.status != MediaStatus.SCANNING:
            return asset.status if asset else "missing"
        key, owner, declared = asset.quarantine_key, asset.owner_id, asset.mime_type
        private = asset.purpose in PRIVATE_PURPOSES
        expected_bytes, expected_sha = asset.bytes, asset.sha256
    reason: str | None = None
    variants: list[dict[str, object]] = []
    width = height = None
    try:
        data = await storage.read_quarantine(key, max_bytes=expected_bytes)
        if data is None:
            raise RejectedMediaError(RejectionReason.PROCESSING_FAILED)
        verify(
            data,
            declared_type=declared,
            declared_bytes=expected_bytes,
            declared_sha256=expected_sha,
        )
        if not await scanner.scan(data):
            raise RejectedMediaError(RejectionReason.MALWARE)
        processed = process_image(data)
        width, height = processed.width, processed.height
        for variant in processed.variants:
            if private:  # message attachments: never in the public bucket (BL-3.05)
                private_key = f"pm/{owner}/{media_id}/{variant.width}.webp"
                await storage.write_private(private_key, variant.data, "image/webp")
                variants.append(
                    {
                        "width": variant.width,
                        "height": variant.height,
                        "key": private_key,
                        "private": True,
                    }
                )
                continue
            public_key = f"m/{owner}/{media_id}/{variant.width}.webp"
            await storage.write_public(public_key, variant.data, "image/webp")
            variants.append(
                {
                    "width": variant.width,
                    "height": variant.height,
                    "key": public_key,
                    "url": storage.public_url(public_key),
                }
            )
    except ObjectTooLargeError:
        reason = RejectionReason.TOO_LARGE
    except RejectedMediaError as rejected:
        reason = rejected.reason
    await storage.delete_quarantine(key)
    async with sessionmaker() as session, session.begin():
        values: dict[str, object] = {"processed_at": func.now()}
        if reason is None:
            values |= {
                "status": MediaStatus.READY,
                "variants": variants,
                "width": width,
                "height": height,
            }
        else:
            values |= {"status": MediaStatus.REJECTED, "rejection_reason": reason}
        await session.execute(
            update(MediaAsset)
            .where(MediaAsset.id == media_id, MediaAsset.status == MediaStatus.SCANNING)
            .values(**values)
        )
        platform.record_event(
            session,
            aggregate_type="media",
            aggregate_id=media_id,
            event_type="media.ready" if reason is None else "media.rejected",
            payload={"media_id": str(media_id), "owner_id": str(owner), "reason": reason},
        )
    if reason is not None:
        for written in variants:  # a rejection after partial writes leaves nothing reachable
            if written.get("private"):
                await storage.delete_private(str(written["key"]))
            else:
                await storage.delete_public(str(written["key"]))
        logger.info("media rejected", extra={"reason": reason})
    return MediaStatus.READY if reason is None else MediaStatus.REJECTED


def make_handlers(
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: ObjectStorage | None,
    scanner: MalwareScanner,
) -> dict[str, platform.JobHandler]:
    async def handle(job: platform.Job) -> None:
        if storage is None:
            raise platform.PermanentJobError("media storage is not configured")
        await process(sessionmaker, storage, scanner, uuid.UUID(str(job.payload["media_id"])))

    async def delete_objects(job: platform.Job) -> None:
        if storage is None:
            raise platform.PermanentJobError("media storage is not configured")
        for key in job.payload.get("public_keys") or []:
            await storage.delete_public(str(key))
        for key in job.payload.get("private_keys") or []:
            await storage.delete_private(str(key))
        for key in job.payload.get("quarantine_keys") or []:
            await storage.delete_quarantine(str(key))

    return {PROCESS_JOB: handle, DELETE_OBJECTS_JOB: delete_objects}


async def schedule_owner_erasure(session: AsyncSession, owner_id: uuid.UUID) -> int:
    """Queue deletion of every stored object of an owner's media (account deletion saga); the
    rows themselves go with the account. Returns the number of assets."""
    assets = (
        await session.scalars(select(MediaAsset).where(MediaAsset.owner_id == owner_id))
    ).all()
    public, private = _keys(assets)
    quarantine = [a.quarantine_key for a in assets if a.status != MediaStatus.READY]
    for start in range(0, max(len(public), len(private), len(quarantine)), 200):
        await platform.enqueue(
            session,
            queue="default",
            kind=DELETE_OBJECTS_JOB,
            payload={
                "public_keys": public[start : start + 200],
                "private_keys": private[start : start + 200],
                "quarantine_keys": quarantine[start : start + 200],
            },
        )
    return len(assets)


# ─────────────────────────────── for other modules ───────────────────────────────


async def refs(
    session: AsyncSession, media_ids: Sequence[uuid.UUID], *, sign: Signer | None = None
) -> dict[uuid.UUID, MediaRef]:
    """Renderable refs. Private media get a signed URL only when ``sign`` is given: pass it only
    after authorizing the viewer for the content that references the media."""
    if not media_ids:
        return {}
    rows = await session.scalars(select(MediaAsset).where(MediaAsset.id.in_(set(media_ids))))
    return {row.id: _ref(row, sign) for row in rows}


async def erase_assets(session: AsyncSession, media_ids: Sequence[uuid.UUID]) -> None:
    """Delete assets and queue deletion of their stored objects (content hard-deleted by its
    owning module)."""
    if not media_ids:
        return
    assets = (
        await session.scalars(select(MediaAsset).where(MediaAsset.id.in_(set(media_ids))))
    ).all()
    public, private = _keys(assets)
    quarantine = [a.quarantine_key for a in assets if a.status != MediaStatus.READY]
    if public or private or quarantine:
        await platform.enqueue(
            session,
            queue="default",
            kind=DELETE_OBJECTS_JOB,
            payload={
                "public_keys": public,
                "private_keys": private,
                "quarantine_keys": quarantine,
            },
        )
    await session.execute(delete(MediaAsset).where(MediaAsset.id.in_(set(media_ids))))


async def usable_ids(
    session: AsyncSession, owner_id: uuid.UUID, media_ids: Sequence[uuid.UUID], purpose: str
) -> set[uuid.UUID]:
    """The given media the owner may attach for ``purpose`` (uploaded and not rejected)."""
    if not media_ids:
        return set()
    rows = await session.scalars(
        select(MediaAsset.id).where(
            MediaAsset.id.in_(set(media_ids)),
            MediaAsset.owner_id == owner_id,
            MediaAsset.purpose == purpose,
            MediaAsset.status.in_([MediaStatus.SCANNING, MediaStatus.READY]),
        )
    )
    return set(rows)


async def purge_expired(session: AsyncSession) -> int:
    """Abandoned uploads after a day; rejected records after 30 days (docs/04 §14)."""
    return await platform.delete_batch(
        session,
        MediaAsset,
        (MediaAsset.status == MediaStatus.PENDING_UPLOAD)
        & (MediaAsset.created_at < platform.ago(days=1)),
    ) + await platform.delete_batch(
        session,
        MediaAsset,
        (MediaAsset.status == MediaStatus.REJECTED)
        & (MediaAsset.created_at < platform.ago(days=30)),
    )
