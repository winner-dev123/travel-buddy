"""A stand-in for Apple's App Store signing chain (tests only): root → intermediate → leaf, with
Apple's marker extensions, and a signer producing ES256 JWS with the ``x5c`` header."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.serialization import Encoding
from cryptography.x509.oid import NameOID

from app.modules.billing.apple import INTERMEDIATE_MARKER, LEAF_MARKER


def _name(common: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common)])


def _cert(
    subject: str,
    key: ec.EllipticCurvePrivateKey,
    issuer: str,
    issuer_key: ec.EllipticCurvePrivateKey,
    *,
    marker: x509.ObjectIdentifier | None,
    ca: bool,
    not_after: datetime,
) -> x509.Certificate:
    now = datetime.now(tz=UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(_name(subject))
        .issuer_name(_name(issuer))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    )
    if marker is not None:
        builder = builder.add_extension(
            x509.UnrecognizedExtension(marker, b"\x05\x00"), critical=False
        )
    return builder.sign(issuer_key, hashes.SHA256())


@dataclass
class AppleChain:
    root: x509.Certificate
    intermediate: x509.Certificate
    leaf: x509.Certificate
    leaf_key: ec.EllipticCurvePrivateKey

    @classmethod
    def create(
        cls, *, leaf_marker: bool = True, leaf_expires_in: timedelta = timedelta(days=365)
    ) -> AppleChain:
        root_key = ec.generate_private_key(ec.SECP256R1())
        mid_key = ec.generate_private_key(ec.SECP256R1())
        leaf_key = ec.generate_private_key(ec.SECP256R1())
        later = datetime.now(tz=UTC) + timedelta(days=3650)
        root = _cert(
            "Test Apple Root CA - G3",
            root_key,
            "Test Apple Root CA - G3",
            root_key,
            marker=None,
            ca=True,
            not_after=later,
        )
        intermediate = _cert(
            "Test Apple WWDR CA",
            mid_key,
            "Test Apple Root CA - G3",
            root_key,
            marker=INTERMEDIATE_MARKER,
            ca=True,
            not_after=later,
        )
        leaf = _cert(
            "Test Prod ECC Mac App Store",
            leaf_key,
            "Test Apple WWDR CA",
            mid_key,
            marker=LEAF_MARKER if leaf_marker else None,
            ca=False,
            not_after=datetime.now(tz=UTC) + leaf_expires_in,
        )
        return cls(root=root, intermediate=intermediate, leaf=leaf, leaf_key=leaf_key)

    @property
    def root_fingerprint(self) -> str:
        return hashlib.sha256(self.root.public_bytes(Encoding.DER)).hexdigest()

    def sign(self, payload: dict[str, Any]) -> str:
        def part(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).decode().rstrip("=")

        header = {
            "alg": "ES256",
            "x5c": [
                base64.b64encode(c.public_bytes(Encoding.DER)).decode()
                for c in (self.leaf, self.intermediate, self.root)
            ],
        }
        signing_input = f"{part(json.dumps(header).encode())}.{part(json.dumps(payload).encode())}"
        r, s = decode_dss_signature(
            self.leaf_key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256()))
        )
        return f"{signing_input}.{part(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"


def transaction(
    *,
    bundle_id: str,
    product_id: str,
    original_transaction_id: str,
    transaction_id: str | None = None,
    expires_in: timedelta = timedelta(days=30),
    revoked: bool = False,
) -> dict[str, Any]:
    now = datetime.now(tz=UTC)
    payload: dict[str, Any] = {
        "bundleId": bundle_id,
        "productId": product_id,
        "originalTransactionId": original_transaction_id,
        "transactionId": transaction_id or f"{original_transaction_id}-1",
        "purchaseDate": int(now.timestamp() * 1000),
        "expiresDate": int((now + expires_in).timestamp() * 1000),
        "type": "Auto-Renewable Subscription",
        "environment": "Sandbox",
    }
    if revoked:
        payload["revocationDate"] = int(now.timestamp() * 1000)
    return payload
