"""Platform access tokens and OIDC ID-token verification (threats T-AUTH-01/03)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.errors import AppError, ErrorCode
from app.core.security.access_tokens import AUDIENCE, ISSUER, AccessTokenService
from app.core.time import FixedClock
from app.modules.identity.adapters.dev_idp import DEV_AUDIENCE, DEV_ISSUER, DevIdentityProvider
from app.modules.identity.adapters.oidc import IssuerConfig, OidcVerifier, StaticKeyProvider

NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


def _service(clock: FixedClock, key: Ed25519PrivateKey | None = None) -> AccessTokenService:
    return AccessTokenService(
        key or Ed25519PrivateKey.generate(), key_id="k1", ttl=timedelta(minutes=15), clock=clock
    )


def _issue(service: AccessTokenService) -> str:
    token, _ = service.issue(
        user_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        roles=frozenset({"moderator"}),
        amr=frozenset({"otp"}),
        auth_time=NOW,
        email_verified=True,
        age_assured=True,
    )
    return token


def _code(excinfo: pytest.ExceptionInfo[AppError]) -> ErrorCode:
    return excinfo.value.code


class TestAccessTokens:
    def test_round_trip(self) -> None:
        clock = FixedClock(NOW)
        service = _service(clock)
        claims = service.verify(_issue(service))
        assert claims.roles == frozenset({"moderator"})
        assert claims.amr == frozenset({"otp"})
        assert claims.email_verified
        assert claims.age_assured
        assert claims.expires_at == NOW + timedelta(minutes=15)

    def test_expiry_uses_injected_clock(self) -> None:
        clock = FixedClock(NOW)
        service = _service(clock)
        token = _issue(service)
        clock.set(NOW + timedelta(minutes=15, seconds=29))  # within 30 s skew
        service.verify(token)
        clock.set(NOW + timedelta(minutes=15, seconds=31))
        with pytest.raises(AppError) as excinfo:
            service.verify(token)
        assert _code(excinfo) is ErrorCode.TOKEN_EXPIRED

    @pytest.mark.security
    def test_token_signed_by_another_key_rejected(self) -> None:
        clock = FixedClock(NOW)
        other = _issue(_service(clock))
        with pytest.raises(AppError) as excinfo:
            _service(clock).verify(other)
        assert _code(excinfo) is ErrorCode.TOKEN_INVALID

    @pytest.mark.security
    def test_alg_none_and_wrong_audience_rejected(self) -> None:
        clock = FixedClock(NOW)
        service = _service(clock)
        payload = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": str(uuid.uuid4()),
            "sid": str(uuid.uuid4()),
            "iat": int(NOW.timestamp()),
            "exp": int((NOW + timedelta(minutes=5)).timestamp()),
        }
        unsigned = jwt.encode(payload, key=None, algorithm="none", headers={"kid": "k1"})
        with pytest.raises(AppError):
            service.verify(unsigned)
        key = Ed25519PrivateKey.generate()
        wrong_aud = jwt.encode(
            {**payload, "aud": "someone-else"}, key, algorithm="EdDSA", headers={"kid": "k1"}
        )
        with pytest.raises(AppError):
            _service(clock, key).verify(wrong_aud)

    @pytest.mark.parametrize("garbage", ["", "not-a-jwt", "a.b.c"])
    def test_garbage_rejected(self, garbage: str) -> None:
        with pytest.raises(AppError) as excinfo:
            _service(FixedClock(NOW)).verify(garbage)
        assert _code(excinfo) is ErrorCode.TOKEN_INVALID


class TestOidcVerifier:
    def _verifier(self, clock: FixedClock) -> tuple[DevIdentityProvider, OidcVerifier]:
        idp = DevIdentityProvider(clock)
        return idp, OidcVerifier([idp.issuer_config()], now=lambda: clock.now().timestamp())

    async def test_valid_dev_token(self) -> None:
        clock = FixedClock(datetime.now(tz=UTC))
        idp, verifier = self._verifier(clock)
        token, _ = idp.mint(sub="abc", email="Ana@Example.com", name="Ana", nonce="n1")
        identity = await verifier.verify(token, expected_nonce="n1")
        assert identity.issuer == DEV_ISSUER
        assert identity.subject == "abc"
        assert identity.email == "ana@example.com"  # normalized
        assert identity.method == "dev"
        assert identity.amr == frozenset({"dev"})

    @pytest.mark.security
    async def test_nonce_mismatch_rejected(self) -> None:
        clock = FixedClock(datetime.now(tz=UTC))
        idp, verifier = self._verifier(clock)
        token, _ = idp.mint(sub="abc", email="a@example.com", nonce="n1")
        with pytest.raises(AppError) as excinfo:
            await verifier.verify(token, expected_nonce="other")
        assert _code(excinfo) is ErrorCode.TOKEN_INVALID

    @pytest.mark.security
    async def test_untrusted_issuer_rejected(self) -> None:
        key = Ed25519PrivateKey.generate()
        now = int(datetime.now(tz=UTC).timestamp())
        token = jwt.encode(
            {
                "iss": "https://evil.example",
                "aud": DEV_AUDIENCE,
                "sub": "x",
                "iat": now,
                "exp": now + 300,
            },
            key,
            algorithm="EdDSA",
            headers={"kid": "dev-1"},
        )
        _, verifier = self._verifier(FixedClock(datetime.now(tz=UTC)))
        with pytest.raises(AppError, match="not trusted"):
            await verifier.verify(token, expected_nonce=None)

    @pytest.mark.security
    async def test_hmac_algorithm_rejected_even_for_trusted_issuer(self) -> None:
        now = int(datetime.now(tz=UTC).timestamp())
        token = jwt.encode(
            {"iss": DEV_ISSUER, "aud": DEV_AUDIENCE, "sub": "x", "iat": now, "exp": now + 300},
            "shared-secret-guessing-attack-0123456789",
            algorithm="HS256",
            headers={"kid": "dev-1"},
        )
        _, verifier = self._verifier(FixedClock(datetime.now(tz=UTC)))
        with pytest.raises(AppError, match="disallowed algorithm"):
            await verifier.verify(token, expected_nonce=None)

    @pytest.mark.security
    async def test_wrong_audience_and_unknown_kid_rejected(self) -> None:
        key = Ed25519PrivateKey.generate()
        verifier = OidcVerifier(
            [
                IssuerConfig(
                    issuer="https://idp.example",
                    audiences=["travelbuddy"],
                    algorithms=["EdDSA"],
                    keys=StaticKeyProvider({"k": key.public_key()}),
                    method="oidc",
                )
            ]
        )
        now = int(datetime.now(tz=UTC).timestamp())
        base = {"iss": "https://idp.example", "sub": "x", "iat": now, "exp": now + 300}
        wrong_aud = jwt.encode(
            {**base, "aud": "other-app"}, key, algorithm="EdDSA", headers={"kid": "k"}
        )
        with pytest.raises(AppError):
            await verifier.verify(wrong_aud, expected_nonce=None)
        unknown_kid = jwt.encode(
            {**base, "aud": "travelbuddy"}, key, algorithm="EdDSA", headers={"kid": "zz"}
        )
        with pytest.raises(AppError, match="Unknown signing key"):
            await verifier.verify(unknown_kid, expected_nonce=None)

    async def test_expired_id_token(self) -> None:
        clock = FixedClock(datetime.now(tz=UTC) - timedelta(hours=1))
        idp, verifier = self._verifier(clock)
        token, _ = idp.mint(sub="abc", email="a@example.com")  # expired 50 minutes ago (real time)
        with pytest.raises(AppError) as excinfo:
            await verifier.verify(token, expected_nonce=None)
        assert _code(excinfo) is ErrorCode.TOKEN_EXPIRED

    def test_dev_jwks_shape(self) -> None:
        jwks = DevIdentityProvider(FixedClock(NOW)).jwks()
        (key,) = jwks["keys"]
        assert key["kty"] == "OKP"
        assert key["crv"] == "Ed25519"
        assert key["kid"] == "dev-1"
        assert len(key["x"]) == 43  # 32 raw bytes, base64url without padding
