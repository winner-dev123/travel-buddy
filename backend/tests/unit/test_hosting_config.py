"""Hosting-related configuration: optional Redis, single-line PEM keys, Supabase Auth claims."""

from __future__ import annotations

from datetime import UTC, datetime

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.core.errors import AppError, ErrorCode
from app.core.security.access_tokens import load_ed25519_private_key
from app.main import create_app
from app.modules.identity.adapters.oidc import IssuerConfig, OidcVerifier, StaticKeyProvider
from tests.conftest import ed25519_test_pem, make_identity_settings, make_settings

SUPABASE_ISSUER = "https://abcdefghijkl.supabase.co/auth/v1"


def test_readiness_skips_redis_when_not_configured() -> None:
    app = create_app(make_settings(redis_url=""), identity_settings=make_identity_settings())
    assert set(app.state.readiness_checks) == {"database"}
    assert app.state.redis is None


def test_readiness_includes_redis_when_configured() -> None:
    app = create_app(make_settings(), identity_settings=make_identity_settings())
    assert set(app.state.readiness_checks) == {"database", "redis"}


def test_pem_key_accepted_as_single_line_with_escaped_newlines() -> None:
    pem = ed25519_test_pem()
    single_line = pem.strip().replace("\n", "\\n")
    assert "\n" not in single_line
    assert load_ed25519_private_key(single_line).public_key() is not None


def _supabase_verifier() -> tuple[ec.EllipticCurvePrivateKey, OidcVerifier]:
    key = ec.generate_private_key(ec.SECP256R1())
    verifier = OidcVerifier(
        [
            IssuerConfig(
                issuer=SUPABASE_ISSUER,
                audiences=["authenticated"],
                algorithms=["ES256"],
                keys=StaticKeyProvider({"kid-1": key.public_key()}),
                method="oidc",
            )
        ]
    )
    return key, verifier


def _supabase_token(key: ec.EllipticCurvePrivateKey, **extra: object) -> str:
    now = int(datetime.now(tz=UTC).timestamp())
    claims: dict[str, object] = {
        "iss": SUPABASE_ISSUER,
        "aud": "authenticated",
        "sub": "6f1c2a4e-7b1d-4c3a-9e2f-0a1b2c3d4e5f",
        "iat": now,
        "exp": now + 3600,
        "email": "ana@example.com",
        "role": "authenticated",
        "aal": "aal1",
        "amr": [{"method": "password", "timestamp": now}],
        "user_metadata": {"email_verified": True},
        "is_anonymous": False,
    }
    claims.update(extra)
    return jwt.encode(claims, key, algorithm="ES256", headers={"kid": "kid-1"})


async def test_supabase_auth_token_claims_are_mapped() -> None:
    key, verifier = _supabase_verifier()
    # ``email_verified`` at the top level is added by the custom access token hook (migration 0003).
    token = _supabase_token(
        key, email_verified=True, user_metadata={"full_name": "Ana Souza", "email_verified": True}
    )
    identity = await verifier.verify(token, expected_nonce=None)
    assert identity.amr == frozenset({"password"})
    assert identity.email_verified is True
    assert identity.email == "ana@example.com"
    assert identity.name == "Ana Souza"


@pytest.mark.security
async def test_user_metadata_email_verified_is_not_trusted() -> None:
    """``user_metadata`` is user-writable in Supabase (``auth.updateUser``); never trust it."""
    key, verifier = _supabase_verifier()
    token = _supabase_token(key, user_metadata={"email_verified": True})
    assert (await verifier.verify(token, expected_nonce=None)).email_verified is False


@pytest.mark.req("ADM-007")
async def test_supabase_aal2_is_recorded_as_mfa() -> None:
    key, verifier = _supabase_verifier()
    now = int(datetime.now(tz=UTC).timestamp())
    token = _supabase_token(
        key,
        aal="aal2",
        amr=[
            {"method": "totp", "timestamp": now - 5},
            {"method": "password", "timestamp": now - 60},
        ],
    )
    identity = await verifier.verify(token, expected_nonce=None)
    assert identity.amr == frozenset({"totp", "password", "mfa"})
    # Supabase has no auth_time; the latest amr timestamp is used instead of iat.
    assert int(identity.auth_time.timestamp()) == now - 5


async def test_aal1_is_not_mfa() -> None:
    key, verifier = _supabase_verifier()
    identity = await verifier.verify(_supabase_token(key, aal="aal1"), expected_nonce=None)
    assert "mfa" not in identity.amr


@pytest.mark.security
async def test_supabase_anonymous_sessions_are_rejected() -> None:
    key, verifier = _supabase_verifier()
    with pytest.raises(AppError) as excinfo:
        await verifier.verify(_supabase_token(key, is_anonymous=True), expected_nonce=None)
    assert excinfo.value.code is ErrorCode.TOKEN_INVALID
