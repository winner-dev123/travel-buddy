"""Object storage port and adapters (docs/02 §11).

Two buckets: *quarantine* receives client uploads through short-lived presigned PUTs and is never
served; *public* holds processed, metadata-free variants served through the CDN. Processed variants
of private media (message attachments, BL-3.05) go to a *private* bucket (by default the quarantine
bucket, under ``pm/``) and are only reachable through short-lived presigned GETs, minted after the
owning module has authorized the viewer.
``LocalStorage`` keeps both in process memory and serves them from a dev-only ASGI app mounted at
``/_dev/storage`` (development and tests; it emulates the external store, so it is not part of the
API contract).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from urllib.parse import urlsplit

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from app.core.time import Clock
from app.modules.media import sigv4

UPLOAD_TTL = timedelta(minutes=5)
PRIVATE_URL_TTL = timedelta(minutes=5)
PUBLIC_CACHE_CONTROL = "public, max-age=31536000, immutable"
PRIVATE_CACHE_CONTROL = "private, max-age=300"


@dataclass(frozen=True, slots=True)
class PresignedPut:
    url: str
    headers: dict[str, str]
    expires_at: datetime


class StorageError(Exception):
    """The store could not be reached or refused the request (retryable)."""


class ObjectTooLargeError(Exception):
    pass


class ObjectStorage(Protocol):
    def presign_put(self, key: str, *, content_type: str, content_length: int) -> PresignedPut: ...

    async def quarantine_size(self, key: str) -> int | None: ...

    async def read_quarantine(self, key: str, *, max_bytes: int) -> bytes | None: ...

    async def delete_quarantine(self, key: str) -> None: ...

    async def write_public(self, key: str, data: bytes, content_type: str) -> None: ...

    async def delete_public(self, key: str) -> None: ...

    def public_url(self, key: str) -> str: ...

    async def write_private(self, key: str, data: bytes, content_type: str) -> None: ...

    async def delete_private(self, key: str) -> None: ...

    def presign_get(self, key: str) -> tuple[str, datetime]: ...


# ─────────────────────────────── S3-compatible ───────────────────────────────


class S3Storage:
    def __init__(
        self,
        *,
        endpoint: str,
        region: str,
        access_key: str,
        secret: str,
        quarantine_bucket: str,
        public_bucket: str,
        public_base_url: str,
        http: httpx.AsyncClient,
        clock: Clock,
        private_bucket: str | None = None,
    ) -> None:
        parts = urlsplit(endpoint.rstrip("/"))
        self._scheme, self._host, self._base_path = parts.scheme, parts.netloc, parts.path
        self._region, self._key, self._secret = region, access_key, secret
        self._quarantine, self._public = quarantine_bucket, public_bucket
        self._private = private_bucket or quarantine_bucket
        self._public_base = public_base_url.rstrip("/")
        self._http, self._clock = http, clock

    def _path(self, bucket: str, key: str) -> str:
        return f"{self._base_path}/{bucket}/{key}"

    def _url(self, bucket: str, key: str) -> str:
        return f"{self._scheme}://{self._host}{sigv4.canonical_path(self._path(bucket, key))}"

    def presign_put(self, key: str, *, content_type: str, content_length: int) -> PresignedPut:
        now = self._clock.now()
        headers = {"Content-Type": content_type, "Content-Length": str(content_length)}
        url = sigv4.presign_url(
            method="PUT",
            scheme=self._scheme,
            host=self._host,
            path=self._path(self._quarantine, key),
            access_key=self._key,
            secret=self._secret,
            region=self._region,
            expires_seconds=int(UPLOAD_TTL.total_seconds()),
            at=now,
            signed_headers=headers,
        )
        return PresignedPut(url=url, headers=headers, expires_at=now + UPLOAD_TTL)

    async def _send(
        self,
        method: str,
        bucket: str,
        key: str,
        *,
        body: bytes = b"",
        extra: dict[str, str] | None = None,
    ) -> httpx.Response:
        headers = sigv4.signed_headers(
            method=method,
            host=self._host,
            path=self._path(bucket, key),
            access_key=self._key,
            secret=self._secret,
            region=self._region,
            at=self._clock.now(),
            payload_hash=hashlib.sha256(body).hexdigest(),
            extra_headers=extra,
        )
        try:
            return await self._http.request(
                method, self._url(bucket, key), headers=headers, content=body, timeout=30
            )
        except httpx.HTTPError as exc:
            raise StorageError(type(exc).__name__) from exc

    async def quarantine_size(self, key: str) -> int | None:
        response = await self._send("HEAD", self._quarantine, key)
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise StorageError(f"HEAD answered {response.status_code}")
        return int(response.headers.get("content-length", "0"))

    async def read_quarantine(self, key: str, *, max_bytes: int) -> bytes | None:
        size = await self.quarantine_size(key)
        if size is None:
            return None
        if size > max_bytes:
            raise ObjectTooLargeError
        response = await self._send("GET", self._quarantine, key)
        if response.status_code != 200:
            raise StorageError(f"GET answered {response.status_code}")
        return response.content[: max_bytes + 1]

    async def delete_quarantine(self, key: str) -> None:
        await self._delete(self._quarantine, key)

    async def write_public(self, key: str, data: bytes, content_type: str) -> None:
        response = await self._send(
            "PUT",
            self._public,
            key,
            body=data,
            extra={"Content-Type": content_type, "Cache-Control": PUBLIC_CACHE_CONTROL},
        )
        if response.status_code not in (200, 201):
            raise StorageError(f"PUT answered {response.status_code}")

    async def delete_public(self, key: str) -> None:
        await self._delete(self._public, key)

    async def _delete(self, bucket: str, key: str) -> None:
        response = await self._send("DELETE", bucket, key)
        if response.status_code not in (200, 204, 404):
            raise StorageError(f"DELETE answered {response.status_code}")

    def public_url(self, key: str) -> str:
        return f"{self._public_base}/{key}"

    async def write_private(self, key: str, data: bytes, content_type: str) -> None:
        response = await self._send(
            "PUT",
            self._private,
            key,
            body=data,
            extra={"Content-Type": content_type, "Cache-Control": PRIVATE_CACHE_CONTROL},
        )
        if response.status_code not in (200, 201):
            raise StorageError(f"PUT answered {response.status_code}")

    async def delete_private(self, key: str) -> None:
        await self._delete(self._private, key)

    def presign_get(self, key: str) -> tuple[str, datetime]:
        now = self._clock.now()
        url = sigv4.presign_url(
            method="GET",
            scheme=self._scheme,
            host=self._host,
            path=self._path(self._private, key),
            access_key=self._key,
            secret=self._secret,
            region=self._region,
            expires_seconds=int(PRIVATE_URL_TTL.total_seconds()),
            at=now,
        )
        return url, now + PRIVATE_URL_TTL


# ─────────────────────────────── in-process (development, tests) ───────────────────────────────


class LocalStorage:
    MOUNT = "/_dev/storage"

    def __init__(self, *, base_url: str, clock: Clock) -> None:
        self._base = base_url.rstrip("/") + self.MOUNT
        self._clock = clock
        self._secret = secrets.token_bytes(32)
        self.quarantine: dict[str, tuple[bytes, str]] = {}
        self.public: dict[str, tuple[bytes, str]] = {}
        self.private: dict[str, tuple[bytes, str]] = {}

    def _token(self, claims: dict[str, object]) -> str:
        body = base64.urlsafe_b64encode(json.dumps(claims, sort_keys=True).encode()).decode()
        signature = hmac.new(self._secret, body.encode(), hashlib.sha256).hexdigest()
        return f"{body}.{signature}"

    def _claims(self, token: str) -> dict[str, object] | None:
        body, _, signature = token.partition(".")
        expected = hmac.new(self._secret, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        claims: dict[str, object] = json.loads(base64.urlsafe_b64decode(body))
        return claims

    def presign_put(self, key: str, *, content_type: str, content_length: int) -> PresignedPut:
        expires_at = self._clock.now() + UPLOAD_TTL
        token = self._token(
            {
                "key": key,
                "type": content_type,
                "length": content_length,
                "exp": expires_at.timestamp(),
            }
        )
        return PresignedPut(
            url=f"{self._base}/upload/{token}",
            headers={"Content-Type": content_type},
            expires_at=expires_at,
        )

    async def quarantine_size(self, key: str) -> int | None:
        found = self.quarantine.get(key)
        return len(found[0]) if found else None

    async def read_quarantine(self, key: str, *, max_bytes: int) -> bytes | None:
        found = self.quarantine.get(key)
        if found is None:
            return None
        if len(found[0]) > max_bytes:
            raise ObjectTooLargeError
        return found[0]

    async def delete_quarantine(self, key: str) -> None:
        self.quarantine.pop(key, None)

    async def write_public(self, key: str, data: bytes, content_type: str) -> None:
        self.public[key] = (data, content_type)

    async def delete_public(self, key: str) -> None:
        self.public.pop(key, None)

    def public_url(self, key: str) -> str:
        return f"{self._base}/public/{key}"

    async def write_private(self, key: str, data: bytes, content_type: str) -> None:
        self.private[key] = (data, content_type)

    async def delete_private(self, key: str) -> None:
        self.private.pop(key, None)

    def presign_get(self, key: str) -> tuple[str, datetime]:
        expires_at = self._clock.now() + PRIVATE_URL_TTL
        token = self._token({"key": key, "exp": expires_at.timestamp(), "op": "get"})
        return f"{self._base}/private/{token}", expires_at

    def asgi_app(self) -> Starlette:
        async def upload(request: Request) -> Response:
            claims = self._claims(request.path_params["token"])
            if (
                claims is None
                or "type" not in claims
                or float(str(claims["exp"])) < self._clock.now().timestamp()
            ):
                return Response("signature expired or invalid", status_code=403)
            if request.headers.get("content-type") != claims["type"]:
                return Response("content-type mismatch", status_code=403)
            body = await request.body()
            if len(body) != claims["length"]:
                return Response("content-length mismatch", status_code=403)
            self.quarantine[str(claims["key"])] = (body, str(claims["type"]))
            return Response(status_code=200)

        async def serve(request: Request) -> Response:
            found = self.public.get(request.path_params["key"])
            if found is None:
                return Response(status_code=404)
            return Response(
                found[0], media_type=found[1], headers={"Cache-Control": PUBLIC_CACHE_CONTROL}
            )

        async def serve_private(request: Request) -> Response:
            claims = self._claims(request.path_params["token"])
            if (
                claims is None
                or claims.get("op") != "get"
                or float(str(claims["exp"])) < self._clock.now().timestamp()
            ):
                return Response("signature expired or invalid", status_code=403)
            found = self.private.get(str(claims["key"]))
            if found is None:
                return Response(status_code=404)
            return Response(
                found[0], media_type=found[1], headers={"Cache-Control": PRIVATE_CACHE_CONTROL}
            )

        return Starlette(
            routes=[
                Route("/upload/{token}", upload, methods=["PUT"]),
                Route("/public/{key:path}", serve, methods=["GET"]),
                Route("/private/{token}", serve_private, methods=["GET"]),
            ]
        )
