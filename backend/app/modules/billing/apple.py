"""App Store signed data: StoreKit 2 transactions and Server Notifications v2 (BILL-003, BILL-007,
BILL-008; ADR-0017).

Apple signs both as JWS (ES256) with the certificate chain in the ``x5c`` header: leaf, Apple's
intermediate, Apple Root CA - G3. A payload is trusted only when

* the root's SHA-256 fingerprint is one we pinned (``APPLE_ROOT_CA_SHA256``; Apple publishes the
  certificate at apple.com/certificateauthority),
* each certificate is signed by the next, valid now, and carries Apple's marker extension (leaf
  ``1.2.840.113635.100.6.11.1``, intermediate ``1.2.840.113635.100.6.2.1``),
* the JWS signature verifies with the leaf key, and the bundle id is ours.

No App Store Server API key is needed for this; that key only matters for pulling history.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Collection, Mapping
from datetime import UTC, datetime
from typing import Any

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.serialization import Encoding

from app.core.errors import AppError, ErrorCode
from app.modules.billing.domain import StoreEvent, SubscriptionStatus
from app.modules.billing.providers import PurchaseClaim, StoreTransaction

LEAF_MARKER = x509.ObjectIdentifier("1.2.840.113635.100.6.11.1")
INTERMEDIATE_MARKER = x509.ObjectIdentifier("1.2.840.113635.100.6.2.1")


class AppleSignatureError(Exception):
    """The signed data is not from Apple for this app (never trust its contents)."""


def _b64url(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def _ms(value: Any) -> datetime | None:
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC) if value is not None else None


class AppleJWSVerifier:
    def __init__(self, *, root_fingerprints: Collection[str], bundle_id: str) -> None:
        self._roots = {fp.replace(":", "").strip().lower() for fp in root_fingerprints if fp}
        self._bundle_id = bundle_id
        if not self._roots:
            raise ValueError("pin at least one Apple root certificate fingerprint")

    @property
    def bundle_id(self) -> str:
        return self._bundle_id

    def decode(self, jws: str, *, now: datetime) -> dict[str, Any]:
        """The verified payload of an Apple JWS; raises :class:`AppleSignatureError`."""
        try:
            header_part, payload_part, signature_part = jws.split(".")
            header = json.loads(_b64url(header_part))
            if header.get("alg") != "ES256":
                raise AppleSignatureError("unexpected algorithm")
            chain = [x509.load_der_x509_certificate(base64.b64decode(c)) for c in header["x5c"]]
            signature = _b64url(signature_part)
            payload = json.loads(_b64url(payload_part))
        except (ValueError, KeyError, TypeError, binascii.Error) as exc:
            raise AppleSignatureError("malformed JWS") from exc
        if len(chain) != 3 or len(signature) != 64 or not isinstance(payload, dict):
            raise AppleSignatureError("malformed JWS")
        leaf, intermediate, root = chain
        fingerprint = hashlib.sha256(root.public_bytes(Encoding.DER)).hexdigest()
        if fingerprint not in self._roots:
            raise AppleSignatureError("untrusted root certificate")
        for cert, issuer in ((leaf, intermediate), (intermediate, root), (root, root)):
            _check_signed_by(cert, issuer)
            if not cert.not_valid_before_utc <= now <= cert.not_valid_after_utc:
                raise AppleSignatureError("certificate outside its validity period")
        for cert, marker in ((leaf, LEAF_MARKER), (intermediate, INTERMEDIATE_MARKER)):
            try:
                cert.extensions.get_extension_for_oid(marker)
            except x509.ExtensionNotFound as exc:
                raise AppleSignatureError("not an App Store certificate") from exc
        key = leaf.public_key()
        if not isinstance(key, ec.EllipticCurvePublicKey):
            raise AppleSignatureError("unexpected key type")
        der = encode_dss_signature(
            int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
        )
        try:
            key.verify(der, f"{header_part}.{payload_part}".encode(), ec.ECDSA(hashes.SHA256()))
        except InvalidSignature as exc:
            raise AppleSignatureError("bad signature") from exc
        return payload


def _check_signed_by(cert: x509.Certificate, issuer: x509.Certificate) -> None:
    if cert.issuer != issuer.subject:
        raise AppleSignatureError("broken certificate chain")
    key = issuer.public_key()
    algorithm = cert.signature_hash_algorithm
    if not isinstance(key, ec.EllipticCurvePublicKey) or algorithm is None:
        raise AppleSignatureError("unexpected certificate key")
    try:
        key.verify(cert.signature, cert.tbs_certificate_bytes, ec.ECDSA(algorithm))
    except InvalidSignature as exc:
        raise AppleSignatureError("broken certificate chain") from exc


def transaction_status(payload: Mapping[str, Any], *, now: datetime) -> SubscriptionStatus:
    """A decoded transaction's state: revoked, expired, or active."""
    if payload.get("revocationDate") is not None:
        return SubscriptionStatus.REVOKED
    expires = _ms(payload.get("expiresDate"))
    if expires is not None and expires <= now:
        return SubscriptionStatus.EXPIRED
    return SubscriptionStatus.ACTIVE


class AppleStoreProvider:
    """``BillingProvider`` for StoreKit 2: the client sends the transaction's JWS
    (``jwsRepresentation``); we verify it ourselves (BILL-003)."""

    def __init__(self, verifier: AppleJWSVerifier) -> None:
        self._verifier = verifier

    async def verify(self, claim: PurchaseClaim, *, now: datetime) -> StoreTransaction:
        try:
            payload = self._verifier.decode(claim.payload, now=now)
        except AppleSignatureError:
            raise AppError(
                ErrorCode.PURCHASE_INVALID, "This purchase couldn't be verified."
            ) from None
        if payload.get("bundleId") != self._verifier.bundle_id:
            raise AppError(ErrorCode.PURCHASE_INVALID, "This purchase is for another app.")
        # Never later than our clock: a store timestamp a little ahead of us (clock skew) would
        # otherwise start the entitlement in the future.
        purchased = min(_ms(payload.get("purchaseDate")) or now, now)
        return StoreTransaction(
            provider="apple",
            sku=str(payload["productId"]),
            original_transaction_id=str(payload["originalTransactionId"]),
            transaction_id=str(payload["transactionId"]),
            purchased_at=purchased,
            status=transaction_status(payload, now=now),
            environment=str(payload.get("environment", "Production")).lower(),
        )


# App Store Server Notifications v2 → normalized store events (docs/07 §4). Types not listed
# (price increases, offers, consumption requests, tests…) need no state change.
def notification_event(notification_type: str, subtype: str | None) -> StoreEvent | None:
    if notification_type == "SUBSCRIBED":
        return StoreEvent.RENEWED
    if notification_type == "DID_RENEW":
        return StoreEvent.RECOVERED if subtype == "BILLING_RECOVERY" else StoreEvent.RENEWED
    if notification_type == "DID_CHANGE_RENEWAL_STATUS":
        return {
            "AUTO_RENEW_DISABLED": StoreEvent.AUTO_RENEW_OFF,
            "AUTO_RENEW_ENABLED": StoreEvent.AUTO_RENEW_ON,
        }.get(subtype or "")
    if notification_type == "DID_FAIL_TO_RENEW":
        return StoreEvent.GRACE if subtype == "GRACE_PERIOD" else StoreEvent.BILLING_RETRY
    if notification_type == "GRACE_PERIOD_EXPIRED":
        return StoreEvent.BILLING_RETRY
    if notification_type == "EXPIRED":
        return StoreEvent.EXPIRED
    if notification_type in ("REFUND", "REVOKE"):
        return StoreEvent.REFUNDED
    return None


def signed_date(payload: Mapping[str, Any]) -> datetime | None:
    return _ms(payload.get("signedDate"))
