"""DEVELOPMENT-ONLY identity provider (ADR-0003; contract ``/v1/dev/idp/*``).

Mints OIDC-style ID tokens so local apps and tests can sign in without a real IdP. Tokens go
through the same :class:`OidcVerifier` as production tokens. The signing key is deterministic and
public by construction; it is only accepted when ``DEV_IDP_ENABLED`` is true, which the settings
guard refuses outside development/test (threat T-AUTH-08).
"""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.time import Clock
from app.modules.identity.adapters.oidc import IssuerConfig, StaticKeyProvider

DEV_ISSUER = "urn:travelbuddy:dev-idp"
DEV_AUDIENCE = "travelbuddy-api"
DEV_KEY_ID = "dev-1"
DEV_TOKEN_TTL = timedelta(minutes=10)
_DEV_KEY_LABEL = b"travelbuddy-development-only-dev-idp-key-v1"


class DevIdentityProvider:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._private_key = Ed25519PrivateKey.from_private_bytes(
            hashlib.sha256(_DEV_KEY_LABEL).digest()
        )
        self._public_key = self._private_key.public_key()

    def mint(
        self,
        *,
        sub: str,
        email: str,
        email_verified: bool = True,
        name: str | None = None,
        nonce: str | None = None,
    ) -> tuple[str, datetime]:
        now = self._clock.now()
        expires_at = now + DEV_TOKEN_TTL
        claims: dict[str, Any] = {
            "iss": DEV_ISSUER,
            "aud": DEV_AUDIENCE,
            "sub": sub,
            "email": email,
            "email_verified": email_verified,
            "iat": int(now.timestamp()),
            "auth_time": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
            "amr": ["dev"],
        }
        if name:
            claims["name"] = name
        if nonce:
            claims["nonce"] = nonce
        token = jwt.encode(
            claims, self._private_key, algorithm="EdDSA", headers={"kid": DEV_KEY_ID}
        )
        return token, expires_at

    def jwks(self) -> dict[str, list[dict[str, str]]]:
        raw = self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )
        x = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
        return {
            "keys": [
                {
                    "kty": "OKP",
                    "crv": "Ed25519",
                    "x": x,
                    "kid": DEV_KEY_ID,
                    "alg": "EdDSA",
                    "use": "sig",
                }
            ]
        }

    def issuer_config(self) -> IssuerConfig:
        return IssuerConfig(
            issuer=DEV_ISSUER,
            audiences=[DEV_AUDIENCE],
            algorithms=["EdDSA"],
            keys=StaticKeyProvider({DEV_KEY_ID: self._public_key}),
            method="dev",
        )
