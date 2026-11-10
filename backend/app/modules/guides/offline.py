"""Offline package integrity and access (pure; BL-4.08, OFF-001, OFF-005).

* The manifest is canonical JSON (sorted keys, no whitespace, UTF-8) signed with Ed25519. Clients
  verify it with the public key published in ``GET /v1/client-config`` (``offline_manifest_keys``,
  matched by ``key_id``), then check each downloaded file's SHA-256 against it.
* Downloads use an HMAC token naming the license and package with an expiry. The download route
  re-checks the license on every file and redirects to a short-lived storage URL.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Final

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

SIGNATURE_ALG: Final = "Ed25519"
FILE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_DEV_LABEL: Final = b"travelbuddy-development-offline-manifest-key"


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def files_hash(files: Sequence[Mapping[str, Any]]) -> str:
    """The manifest's ``sha256``: hash of the canonical file list."""
    return hashlib.sha256(canonical(list(files))).hexdigest()


def development_manifest_key() -> Ed25519PrivateKey:
    """Deterministic key for development and test only (never used in staging/production)."""
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(_DEV_LABEL).digest())


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


class ManifestSigner:
    def __init__(self, private_key: Ed25519PrivateKey, key_id: str) -> None:
        self._key = private_key
        self.key_id = key_id

    def sign(self, body: Mapping[str, Any]) -> dict[str, Any]:
        unsigned = {**body, "signature_alg": SIGNATURE_ALG, "key_id": self.key_id}
        return {**unsigned, "signature": _b64(self._key.sign(canonical(unsigned)))}

    def public_key(self) -> dict[str, str]:
        raw = self._key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )
        return {"key_id": self.key_id, "alg": SIGNATURE_ALG, "public_key": _b64(raw)}


def verify_manifest(manifest: Mapping[str, Any], public_key_b64: str) -> bool:
    """What a client does: check the signature over the canonical manifest without it."""
    unsigned = {k: v for k, v in manifest.items() if k != "signature"}
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        key.verify(base64.b64decode(str(manifest["signature"])), canonical(unsigned))
    except Exception:  # any failure means "not valid"
        return False
    return True


class DownloadTokens:
    """``<payload>.<mac>`` (base64url): license, package and expiry, HMAC-SHA256."""

    def __init__(self, secret: bytes) -> None:
        self._secret = hashlib.sha256(b"offline-downloads\x00" + secret).digest()

    def _mac(self, payload: bytes) -> str:
        digest = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode().rstrip("=")

    def issue(self, license_id: uuid.UUID, package_id: uuid.UUID, expires_at: datetime) -> str:
        payload = canonical(
            {"l": str(license_id), "p": str(package_id), "e": int(expires_at.timestamp())}
        )
        body = base64.urlsafe_b64encode(payload).decode().rstrip("=")
        return f"{body}.{self._mac(payload)}"

    def read(self, token: str, *, now: datetime) -> tuple[uuid.UUID, uuid.UUID] | None:
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
            license_id, package_id = uuid.UUID(claims["l"]), uuid.UUID(claims["p"])
        except (ValueError, KeyError, TypeError):
            return None
        return (license_id, package_id) if expires > now else None
