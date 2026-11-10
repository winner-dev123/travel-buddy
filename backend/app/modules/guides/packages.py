"""Offline packages (BL-4.08; OFF-001, OFF-004, OFF-005).

* **Build** (operator command or job): a ``guide`` package holds the destination's published guides
  in one locale as JSON files plus the catalog places they mention. Files go to private storage
  under ``offline/<package id>/``. An unchanged build is not republished; a changed one becomes
  the next version and retires the previous one.
* **License**: per user, package and device. Re-licensing is idempotent and free; a new version
  of a package the device already holds replaces the old license without using quota; otherwise
  active licenses count against ``offline.packages`` (free 1, premium 15). Premium packages also
  need the content entitlement.
* **Manifest**: signed when issued (Ed25519). Packages past ``license_expires_at`` are no longer
  licensed, listed, described or downloadable (OFF-005).
* **Download**: ``base_url`` carries an HMAC token for one license; each file request re-checks the
  license and redirects to a short-lived storage URL.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ErrorCode
from app.core.time import Clock
from app.modules.billing import service as billing
from app.modules.billing.schemas import QuotaStatusOut
from app.modules.destinations import service as destinations
from app.modules.guides.models import DestinationGuide, OfflinePackage, OfflinePackageLicense
from app.modules.guides.offline import FILE_NAME, DownloadTokens, ManifestSigner, files_hash
from app.modules.guides.schemas import (
    DownloadInfo,
    OfflineLicenseList,
    OfflinePackageLicenseOut,
    OfflinePackageLicenseSummary,
    OfflinePackageList,
    OfflinePackageSummary,
)
from app.modules.guides.service import entitled, guide_document, live
from app.modules.media.service import ObjectStorage
from app.modules.platform import service as platform

DOWNLOAD_TTL = timedelta(hours=6)
_KIND_CONTENT = {
    "guide": "guide",
    "audio_tour": "audio_tour",
    "map_region": "guide",
    "bundle": "guide",
}


def _not_found() -> AppError:
    return AppError(ErrorCode.NOT_FOUND, "Package not found.")


def _unavailable() -> AppError:
    return AppError(ErrorCode.SERVICE_UNAVAILABLE, "Offline downloads aren't available yet.")


def _usable(now: datetime) -> list[Any]:
    return [
        OfflinePackage.status == "published",
        or_(OfflinePackage.license_expires_at.is_(None), OfflinePackage.license_expires_at > now),
    ]


def _active_license(now: datetime) -> list[Any]:
    return [
        OfflinePackageLicense.revoked_at.is_(None),
        or_(OfflinePackageLicense.expires_at.is_(None), OfflinePackageLicense.expires_at > now),
    ]


def _summary(row: OfflinePackage, is_entitled: bool) -> OfflinePackageSummary:
    return OfflinePackageSummary(
        id=row.id,
        destination_id=row.destination_id,
        locale=row.locale,
        kind=row.kind,  # type: ignore[arg-type]
        version=row.version,
        total_bytes=row.total_bytes,
        tier=row.tier,  # type: ignore[arg-type]
        entitled=is_entitled,
        min_app_version=row.min_app_version,
        license_expires_at=row.license_expires_at,
        published_at=row.published_at,  # type: ignore[arg-type]
    )


async def _entitled(
    session: AsyncSession, user_id: uuid.UUID, row: OfflinePackage, now: datetime
) -> bool:
    return await entitled(
        session,
        user_id,
        kind=_KIND_CONTENT[row.kind],  # type: ignore[arg-type]
        content_id=row.id,
        tier=row.tier,
        at=now,
    )


async def offline_usage(session: AsyncSession, user_id: uuid.UUID, at: datetime) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(OfflinePackageLicense)
        .where(OfflinePackageLicense.user_id == user_id, *_active_license(at))
    )
    return int(count or 0)


async def quota_usage(
    session: AsyncSession, user_id: uuid.UUID, at: datetime
) -> dict[billing.Quota, int]:
    return {billing.Quota.OFFLINE_PACKAGES: await offline_usage(session, user_id, at)}


# ─────────────────────────────── build ───────────────────────────────


def _file(name: str, payload: Any) -> tuple[dict[str, Any], bytes]:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    entry = {
        "path": name,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "content_type": "application/json",
    }
    return entry, data


async def build_guide_package(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    destination_id: uuid.UUID,
    locale: str,
    now: datetime,
    min_app_version: str = "1.0.0",
) -> OfflinePackage | None:
    """Package the destination's published guides in ``locale`` (``None`` when there are none)."""
    rows = list(
        await session.scalars(
            select(DestinationGuide)
            .where(
                DestinationGuide.destination_id == destination_id,
                DestinationGuide.locale == locale,
                *live(DestinationGuide, now),
            )
            .order_by(DestinationGuide.slug)
        )
    )
    summaries = await destinations.summaries_by_id(session, [destination_id], [locale])
    if not rows or destination_id not in summaries:
        return None
    destination = summaries[destination_id]
    documents = [guide_document(row, destination) for row in rows]
    place_ids = sorted({p for doc in documents for s in doc.sections for p in s.place_ids}, key=str)
    places = await destinations.place_summaries(session, place_ids, [locale])
    built = [
        _file(
            "index.json",
            {
                "destination": destination.model_dump(mode="json"),
                "locale": locale,
                "guides": [
                    {"id": str(doc.id), "title": doc.title, "file": f"guide-{row.slug}.json"}
                    for doc, row in zip(documents, rows, strict=True)
                ],
            },
        ),
        *(
            _file(f"guide-{row.slug}.json", doc.model_dump(mode="json"))
            for doc, row in zip(documents, rows, strict=True)
        ),
        _file("places.json", [p.model_dump(mode="json") for p in places.values()]),
    ]
    files = [entry for entry, _ in built]
    digest = files_hash(files)
    family = (
        OfflinePackage.destination_id == destination_id,
        OfflinePackage.locale == locale,
        OfflinePackage.kind == "guide",
    )
    current = await session.scalar(
        select(OfflinePackage)
        .where(*family, OfflinePackage.status == "published")
        .order_by(OfflinePackage.version.desc())
        .limit(1)
    )
    if current is not None and current.sha256 == digest:
        return current  # unchanged: keep the published version
    latest = await session.scalar(select(func.max(OfflinePackage.version)).where(*family))
    expiries = [row.rights_expire_at for row in rows if row.rights_expire_at is not None]
    package = OfflinePackage(
        destination_id=destination_id,
        locale=locale,
        kind="guide",
        version=(latest or 0) + 1,
        files=files,
        total_bytes=sum(entry["bytes"] for entry in files),
        sha256=digest,
        tier="free" if all(row.tier == "free" for row in rows) else "premium",
        min_app_version=min_app_version,
        content_license=" + ".join(sorted({row.content_license for row in rows})),
        license_expires_at=min(expiries) if expiries else None,
        status="building",
        created_at=now,
    )
    session.add(package)
    await session.flush()
    for entry, data in built:
        await storage.write_private(
            f"offline/{package.id}/{entry['path']}", data, entry["content_type"]
        )
    await session.execute(
        update(OfflinePackage)
        .where(*family, OfflinePackage.status == "published")
        .values(status="retired")
    )
    package.status = "published"
    package.published_at = now
    await session.flush()
    return package


# ─────────────────────────────── service ───────────────────────────────


class OfflinePackageService:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        clock: Clock,
        storage: ObjectStorage | None,
        signer: ManifestSigner | None,
        tokens: DownloadTokens,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._clock = clock
        self._storage = storage
        self._signer = signer
        self._tokens = tokens

    def public_keys(self) -> list[dict[str, str]]:
        return [self._signer.public_key()] if self._signer is not None else []

    def _manifest(self, row: OfflinePackage, now: datetime) -> dict[str, Any]:
        if self._signer is None:
            raise _unavailable()
        return self._signer.sign(
            {
                "package_id": str(row.id),
                "destination_id": str(row.destination_id),
                "kind": row.kind,
                "locale": row.locale,
                "version": row.version,
                "files": row.files,
                "total_bytes": row.total_bytes,
                "sha256": row.sha256,
                "min_app_version": row.min_app_version,
                "content_license": row.content_license,
                "license_expires_at": (
                    row.license_expires_at.isoformat() if row.license_expires_at else None
                ),
                "issued_at": now.isoformat(),
            }
        )

    async def list_for_destination(
        self, destination_id: uuid.UUID, user_id: uuid.UUID
    ) -> OfflinePackageList:
        now = self._clock.now()
        async with self._sessionmaker() as session:
            if not await destinations.is_active(session, destination_id):
                raise AppError(ErrorCode.NOT_FOUND, "Destination not found.")
            rows = (
                await session.scalars(
                    select(OfflinePackage)
                    .where(OfflinePackage.destination_id == destination_id, *_usable(now))
                    .order_by(OfflinePackage.kind, OfflinePackage.locale)
                )
            ).all()
            return OfflinePackageList(
                data=[_summary(row, await _entitled(session, user_id, row, now)) for row in rows]
            )

    async def _package(
        self, session: AsyncSession, package_id: uuid.UUID, now: datetime
    ) -> OfflinePackage:
        row = await session.scalar(
            select(OfflinePackage).where(OfflinePackage.id == package_id, *_usable(now))
        )
        if row is None:
            raise _not_found()
        return row

    async def license(
        self, user_id: uuid.UUID, package_id: uuid.UUID, device_id: str, *, download_base: str
    ) -> OfflinePackageLicenseOut:
        """``download_base``: the absolute URL of ``/v1/offline-downloads`` on this API."""
        if self._signer is None or self._storage is None:
            raise _unavailable()
        now = self._clock.now()
        async with self._sessionmaker() as session, session.begin():
            row = await self._package(session, package_id, now)
            if not await _entitled(session, user_id, row, now):
                raise AppError(
                    ErrorCode.ENTITLEMENT_REQUIRED,
                    "This download is premium content.",
                    extensions={"entitlement": "guides.premium"},
                )
            await session.execute(select(func.pg_advisory_xact_lock(4203, _lock_key(user_id))))
            existing = await session.scalar(
                select(OfflinePackageLicense)
                .where(
                    OfflinePackageLicense.user_id == user_id,
                    OfflinePackageLicense.package_id == package_id,
                    OfflinePackageLicense.device_id == device_id,
                )
                .with_for_update()
            )
            active = existing is not None and existing.revoked_at is None
            if not active:
                # A newer version of a package this device holds replaces the old license.
                older = list(
                    await session.scalars(
                        select(OfflinePackageLicense)
                        .join(OfflinePackage, OfflinePackage.id == OfflinePackageLicense.package_id)
                        .where(
                            OfflinePackageLicense.user_id == user_id,
                            OfflinePackageLicense.device_id == device_id,
                            OfflinePackage.destination_id == row.destination_id,
                            OfflinePackage.locale == row.locale,
                            OfflinePackage.kind == row.kind,
                            OfflinePackage.id != row.id,
                            *_active_license(now),
                        )
                    )
                )
                for license_row in older:
                    license_row.revoked_at = now
                await session.flush()
                snapshot = await billing.snapshot(session, user_id, at=now)
                used = await offline_usage(session, user_id, now)
                status = snapshot.quota(billing.Quota.OFFLINE_PACKAGES, used=used)
                if status.used >= status.limit:
                    raise AppError(
                        ErrorCode.QUOTA_EXCEEDED,
                        "You've reached your offline download allowance. Remove a download first.",
                        status=HTTPStatus.CONFLICT,
                        extensions={"feature_key": billing.Quota.OFFLINE_PACKAGES.value},
                    )
                if existing is None:
                    existing = OfflinePackageLicense(
                        user_id=user_id, package_id=package_id, device_id=device_id
                    )
                    session.add(existing)
                existing.granted_at = now
                existing.revoked_at = None
                existing.expires_at = row.license_expires_at
                await session.flush()
            assert existing is not None
            snapshot = await billing.snapshot(session, user_id, at=now)
            quota = snapshot.quota(
                billing.Quota.OFFLINE_PACKAGES, used=await offline_usage(session, user_id, now)
            )
            expires = now + DOWNLOAD_TTL
            return OfflinePackageLicenseOut(
                id=existing.id,
                package_id=row.id,
                device_id=device_id,
                granted_at=existing.granted_at,
                expires_at=existing.expires_at,
                manifest=self._manifest(row, now),
                download=DownloadInfo(
                    base_url=(
                        f"{download_base.rstrip('/')}/"
                        f"{self._tokens.issue(existing.id, row.id, expires)}/"
                    ),
                    expires_at=expires,
                ),
                quota=QuotaStatusOut(limit=quota.limit, used=quota.used, resets_at=quota.resets_at),
            )

    async def release(
        self, user_id: uuid.UUID, package_id: uuid.UUID, license_id: uuid.UUID
    ) -> None:
        async with self._sessionmaker() as session, session.begin():
            row = await session.get(OfflinePackageLicense, license_id, with_for_update=True)
            if row is None or row.user_id != user_id or row.package_id != package_id:
                raise AppError(ErrorCode.NOT_FOUND, "License not found.")
            row.revoked_at = row.revoked_at or self._clock.now()

    async def manifest(self, user_id: uuid.UUID, package_id: uuid.UUID) -> dict[str, Any]:
        now = self._clock.now()
        async with self._sessionmaker() as session:
            row = await self._package(session, package_id, now)
            if not await _entitled(session, user_id, row, now):
                raise AppError(
                    ErrorCode.ENTITLEMENT_REQUIRED,
                    "This download is premium content.",
                    extensions={"entitlement": "guides.premium"},
                )
            return self._manifest(row, now)

    async def my_licenses(self, user_id: uuid.UUID) -> OfflineLicenseList:
        now = self._clock.now()
        async with self._sessionmaker() as session:
            rows = (
                await session.execute(
                    select(OfflinePackageLicense, OfflinePackage)
                    .join(OfflinePackage, OfflinePackage.id == OfflinePackageLicense.package_id)
                    .where(OfflinePackageLicense.user_id == user_id, *_active_license(now))
                    .order_by(OfflinePackageLicense.granted_at.desc())
                )
            ).all()
            data = []
            for license_row, package in rows:
                data.append(
                    OfflinePackageLicenseSummary(
                        id=license_row.id,
                        package=_summary(package, await _entitled(session, user_id, package, now)),
                        device_id=license_row.device_id,
                        granted_at=license_row.granted_at,
                        expires_at=license_row.expires_at,
                    )
                )
        return OfflineLicenseList(data=data)

    async def download_url(self, token: str, file: str) -> str:
        """Where to fetch one file of a licensed package (a short-lived storage URL)."""
        if self._storage is None:
            raise _unavailable()
        now = self._clock.now()
        claims = self._tokens.read(token, now=now)
        if claims is None or not FILE_NAME.fullmatch(file):
            raise _not_found()
        license_id, package_id = claims
        async with self._sessionmaker() as session:
            license_row = await session.scalar(
                select(OfflinePackageLicense).where(
                    OfflinePackageLicense.id == license_id,
                    OfflinePackageLicense.package_id == package_id,
                    *_active_license(now),
                )
            )
            package = await session.scalar(
                select(OfflinePackage).where(
                    OfflinePackage.id == package_id,
                    OfflinePackage.status.in_(("published", "retired")),
                    or_(
                        OfflinePackage.license_expires_at.is_(None),
                        OfflinePackage.license_expires_at > now,
                    ),
                )
            )
        if license_row is None or package is None:
            raise _not_found()
        if file not in {entry["path"] for entry in package.files}:
            raise _not_found()
        url, _ = self._storage.presign_get(f"offline/{package_id}/{file}")
        return url


def _lock_key(user_id: uuid.UUID) -> int:
    return int.from_bytes(user_id.bytes[:4], "big", signed=True)


async def purge_expired(session: AsyncSession) -> int:
    """Released licenses are kept 30 days (support), then deleted."""
    return await platform.delete_batch(
        session,
        OfflinePackageLicense,
        OfflinePackageLicense.revoked_at < platform.ago(days=30),
    )
