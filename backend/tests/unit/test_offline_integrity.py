"""Offline manifest signatures and download tokens (BL-4.08; OFF-001, OFF-005)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.modules.guides.offline import (
    DownloadTokens,
    ManifestSigner,
    canonical,
    development_manifest_key,
    files_hash,
    verify_manifest,
)

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


@pytest.mark.req("OFF-001")
def test_manifests_are_signed_over_canonical_json() -> None:
    signer = ManifestSigner(development_manifest_key(), "dev-offline")
    files = [{"path": "index.json", "bytes": 2, "sha256": "a" * 64, "content_type": "x"}]
    manifest = signer.sign({"version": 1, "files": files, "sha256": files_hash(files)})
    key = signer.public_key()
    assert (manifest["signature_alg"], manifest["key_id"]) == ("Ed25519", "dev-offline")
    assert verify_manifest(manifest, key["public_key"])
    assert not verify_manifest({**manifest, "version": 2}, key["public_key"])
    assert not verify_manifest({**manifest, "key_id": "other"}, key["public_key"])
    assert canonical({"b": 1, "a": "é"}) == '{"a":"é","b":1}'.encode()


@pytest.mark.req("OFF-005")
def test_download_tokens_expire_and_resist_tampering() -> None:
    tokens = DownloadTokens(b"secret")
    license_id, package_id = uuid.uuid4(), uuid.uuid4()
    token = tokens.issue(license_id, package_id, NOW + timedelta(hours=1))
    assert tokens.read(token, now=NOW) == (license_id, package_id)
    assert tokens.read(token, now=NOW + timedelta(hours=2)) is None
    assert tokens.read(token[:-2] + "xx", now=NOW) is None
    assert tokens.read("garbage", now=NOW) is None
    assert DownloadTokens(b"other").read(token, now=NOW) is None
