"""S3-compatible storage adapter against a mock endpoint (BL-1.08)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.core.time import FixedClock
from app.modules.media.storage import ObjectTooLargeError, S3Storage, StorageError

AT = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


def _storage(handler: httpx.MockTransport) -> S3Storage:
    return S3Storage(
        endpoint="https://abcd.supabase.co/storage/v1/s3",
        region="eu-west-1",
        access_key="AKIDEXAMPLE",
        secret="secret",
        quarantine_bucket="media-quarantine",
        public_bucket="media-public",
        public_base_url="https://abcd.supabase.co/storage/v1/object/public/media-public/",
        http=httpx.AsyncClient(transport=handler),
        clock=FixedClock(AT),
    )


def test_presigned_put_targets_the_quarantine_bucket_and_signs_type_and_size() -> None:
    storage = _storage(httpx.MockTransport(lambda r: httpx.Response(200)))
    target = storage.presign_put("u1/m1", content_type="image/jpeg", content_length=1234)
    parts = urlsplit(target.url)
    assert parts.netloc == "abcd.supabase.co"
    assert parts.path == "/storage/v1/s3/media-quarantine/u1/m1"
    query = parse_qs(parts.query)
    assert query["X-Amz-Expires"] == ["300"]
    assert query["X-Amz-SignedHeaders"] == ["content-length;content-type;host"]
    assert query["X-Amz-Credential"][0].startswith("AKIDEXAMPLE/20261109/eu-west-1/s3/")
    assert target.headers == {"Content-Type": "image/jpeg", "Content-Length": "1234"}
    assert (target.expires_at - AT).total_seconds() == 300


def test_server_side_calls_are_signed_and_public_urls_use_the_cdn_base() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "HEAD":
            return httpx.Response(200, headers={"content-length": "3"})
        if request.method == "GET":
            return httpx.Response(200, content=b"abc")
        return httpx.Response(200)

    storage = _storage(httpx.MockTransport(handler))
    assert asyncio.run(storage.read_quarantine("u1/m1", max_bytes=10)) == b"abc"
    asyncio.run(storage.write_public("m/u1/m1/800.webp", b"webp", "image/webp"))
    put = seen[-1]
    assert put.method == "PUT"
    assert put.url.path == "/storage/v1/s3/media-public/m/u1/m1/800.webp"
    assert put.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")
    assert "cache-control;content-type;host" in put.headers["authorization"]
    assert put.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert storage.public_url("m/u1/m1/800.webp") == (
        "https://abcd.supabase.co/storage/v1/object/public/media-public/m/u1/m1/800.webp"
    )


def test_missing_oversized_and_failing_objects() -> None:
    def missing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    assert (
        asyncio.run(_storage(httpx.MockTransport(missing)).read_quarantine("k", max_bytes=1))
        is None
    )

    def huge(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-length": "999"})

    with pytest.raises(ObjectTooLargeError):
        asyncio.run(_storage(httpx.MockTransport(huge)).read_quarantine("k", max_bytes=10))

    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with pytest.raises(StorageError):
        asyncio.run(_storage(httpx.MockTransport(broken)).write_public("k", b"x", "image/webp"))
    asyncio.run(_storage(httpx.MockTransport(missing)).delete_quarantine("k"))  # 404 is fine
