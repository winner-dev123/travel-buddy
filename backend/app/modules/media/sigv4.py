"""AWS Signature Version 4 for S3-compatible storage (AWS S3, Cloudflare R2, MinIO, Supabase
Storage's S3 endpoint), without an SDK: presigned URLs for direct client uploads and signed headers
for server-side reads and writes. Verified against AWS's published test vectors (unit tests)."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from datetime import UTC, datetime
from urllib.parse import quote

ALGORITHM = "AWS4-HMAC-SHA256"
UNSIGNED_PAYLOAD = "UNSIGNED-PAYLOAD"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret: str, datestamp: str, region: str, service: str) -> bytes:
    key = _hmac(f"AWS4{secret}".encode(), datestamp)
    for part in (region, service, "aws4_request"):
        key = _hmac(key, part)
    return key


def _encode(value: str, *, safe: str = "-_.~") -> str:
    return quote(value, safe=safe)


def canonical_path(path: str) -> str:
    return _encode(path, safe="/-_.~")


def _signature(
    *,
    method: str,
    path: str,
    query: Mapping[str, str],
    headers: Mapping[str, str],
    payload_hash: str,
    secret: str,
    region: str,
    service: str,
    at: datetime,
) -> tuple[str, str, str]:
    """Returns ``(signature, signed_header_names, credential_scope)``."""
    amz_date = at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    datestamp = amz_date[:8]
    scope = f"{datestamp}/{region}/{service}/aws4_request"
    lowered = {k.lower(): " ".join(v.strip().split()) for k, v in headers.items()}
    names = ";".join(sorted(lowered))
    canonical_query = "&".join(f"{_encode(k)}={_encode(v)}" for k, v in sorted(query.items()))
    canonical_headers = "".join(f"{k}:{lowered[k]}\n" for k in sorted(lowered))
    canonical_request = "\n".join(
        [method, canonical_path(path), canonical_query, canonical_headers, names, payload_hash]
    )
    string_to_sign = "\n".join(
        [ALGORITHM, amz_date, scope, hashlib.sha256(canonical_request.encode()).hexdigest()]
    )
    signature = hmac.new(
        _signing_key(secret, datestamp, region, service), string_to_sign.encode(), hashlib.sha256
    ).hexdigest()
    return signature, names, scope


def presign_url(
    *,
    method: str,
    scheme: str,
    host: str,
    path: str,
    access_key: str,
    secret: str,
    region: str,
    expires_seconds: int,
    at: datetime,
    signed_headers: Mapping[str, str] | None = None,
    service: str = "s3",
) -> str:
    """A query-string-authenticated URL; ``signed_headers`` must be sent exactly as given."""
    headers = {"host": host, **{k.lower(): v for k, v in (signed_headers or {}).items()}}
    amz_date = at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    scope = f"{amz_date[:8]}/{region}/{service}/aws4_request"
    query = {
        "X-Amz-Algorithm": ALGORITHM,
        "X-Amz-Credential": f"{access_key}/{scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(expires_seconds),
        "X-Amz-SignedHeaders": ";".join(sorted(headers)),
    }
    signature, _, _ = _signature(
        method=method,
        path=path,
        query=query,
        headers=headers,
        payload_hash=UNSIGNED_PAYLOAD,
        secret=secret,
        region=region,
        service=service,
        at=at,
    )
    canonical_query = "&".join(f"{_encode(k)}={_encode(v)}" for k, v in sorted(query.items()))
    return f"{scheme}://{host}{canonical_path(path)}?{canonical_query}&X-Amz-Signature={signature}"


def signed_headers(
    *,
    method: str,
    host: str,
    path: str,
    access_key: str,
    secret: str,
    region: str,
    at: datetime,
    payload_hash: str = EMPTY_SHA256,
    extra_headers: Mapping[str, str] | None = None,
    service: str = "s3",
) -> dict[str, str]:
    """Headers (including ``Authorization``) for a server-side request."""
    amz_date = at.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    headers = {
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
        **{k.lower(): v for k, v in (extra_headers or {}).items()},
    }
    signature, names, scope = _signature(
        method=method,
        path=path,
        query={},
        headers=headers,
        payload_hash=payload_hash,
        secret=secret,
        region=region,
        service=service,
        at=at,
    )
    headers["authorization"] = (
        f"{ALGORITHM} Credential={access_key}/{scope}, SignedHeaders={names}, Signature={signature}"
    )
    headers.pop("host")  # httpx sets it from the URL
    return headers
