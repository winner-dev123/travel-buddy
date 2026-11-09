"""HTTP JWKS key provider: fetch, cache, refetch on unknown kid, upstream failure (T-AUTH-01)."""

from __future__ import annotations

import base64
from datetime import UTC, datetime

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.errors import AppError, ErrorCode
from app.modules.identity.adapters.oidc import HttpJwksKeyProvider, IssuerConfig, OidcVerifier

JWKS_URI = "https://idp.example.com/.well-known/jwks.json"


def _jwk(key: Ed25519PrivateKey, kid: str) -> dict[str, str]:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    x = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return {"kty": "OKP", "crv": "Ed25519", "x": x, "kid": kid, "alg": "EdDSA", "use": "sig"}


class _Idp:
    """Fake IdP JWKS endpoint that counts requests and can rotate keys."""

    def __init__(self) -> None:
        self.keys: dict[str, Ed25519PrivateKey] = {"k1": Ed25519PrivateKey.generate()}
        self.requests = 0
        self.fail = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        if self.fail:
            return httpx.Response(503)
        return httpx.Response(200, json={"keys": [_jwk(k, kid) for kid, k in self.keys.items()]})

    def token(self, kid: str) -> str:
        now = int(datetime.now(tz=UTC).timestamp())
        claims = {
            "iss": "https://idp.example.com/",
            "aud": "travelbuddy",
            "sub": "u1",
            "iat": now,
            "exp": now + 300,
            "email": "u1@example.com",
            "email_verified": True,
        }
        return jwt.encode(claims, self.keys[kid], algorithm="EdDSA", headers={"kid": kid})


def _verifier(idp: _Idp, *, min_refresh: float = 0.0) -> OidcVerifier:
    client = httpx.AsyncClient(transport=httpx.MockTransport(idp.handler))
    provider = HttpJwksKeyProvider(JWKS_URI, client, min_refresh_seconds=min_refresh)
    return OidcVerifier(
        [
            IssuerConfig(
                issuer="https://idp.example.com/",
                audiences=["travelbuddy"],
                algorithms=["EdDSA"],
                keys=provider,
                method="google",
            )
        ]
    )


async def test_fetches_once_and_caches() -> None:
    idp = _Idp()
    verifier = _verifier(idp)
    for _ in range(3):
        identity = await verifier.verify(idp.token("k1"), expected_nonce=None)
    assert identity.method == "google"
    assert identity.email_verified
    assert idp.requests == 1


async def test_refetches_when_idp_rotates_keys() -> None:
    idp = _Idp()
    verifier = _verifier(idp)
    await verifier.verify(idp.token("k1"), expected_nonce=None)
    idp.keys["k2"] = Ed25519PrivateKey.generate()  # rotation: new kid appears
    await verifier.verify(idp.token("k2"), expected_nonce=None)
    assert idp.requests == 2


@pytest.mark.security
async def test_unknown_kid_refetch_is_rate_limited() -> None:
    idp = _Idp()
    verifier = _verifier(idp, min_refresh=60)
    await verifier.verify(idp.token("k1"), expected_nonce=None)
    idp.keys["forged"] = Ed25519PrivateKey.generate()
    forged = idp.token("forged")
    del idp.keys["forged"]
    for _ in range(5):  # an attacker spraying unknown kids cannot force refetches
        with pytest.raises(AppError, match="Unknown signing key"):
            await verifier.verify(forged, expected_nonce=None)
    assert idp.requests == 1


async def test_upstream_failure_is_a_503_problem() -> None:
    idp = _Idp()
    idp.fail = True
    with pytest.raises(AppError) as excinfo:
        await _verifier(idp).verify(idp.token("k1"), expected_nonce=None)
    assert excinfo.value.code is ErrorCode.UPSTREAM_UNAVAILABLE
    assert excinfo.value.status == 503
