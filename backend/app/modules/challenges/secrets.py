"""Reward secrets (discount codes) at rest (CHAL-015, docs/04 ``reward_fulfillments``).

AES-256-GCM under a key derived (HKDF, own label) from a server secret. The fulfillment id is the
associated data, so a ciphertext copied onto another row does not decrypt. Plaintext goes only to
the recipient (``GET /v1/users/me/rewards``) and is never logged or audited.
"""

from __future__ import annotations

import os
import uuid

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_INFO = b"travelbuddy challenge reward secret v1"


class RewardSecretCipher:
    def __init__(self, secret: str) -> None:
        key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_INFO).derive(
            secret.encode("utf-8")
        )
        self._aead = AESGCM(key)

    def encrypt(self, value: str, *, fulfillment_id: uuid.UUID) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._aead.encrypt(nonce, value.encode("utf-8"), fulfillment_id.bytes)

    def decrypt(self, blob: bytes, *, fulfillment_id: uuid.UUID) -> str:
        return self._aead.decrypt(blob[:12], blob[12:], fulfillment_id.bytes).decode("utf-8")
