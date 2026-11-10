"""Firebase Authentication as the identity provider (ADR-0028): token claims, the account check at
sign-in (AUTH-005), Firebase account deletion (AUTH-010) and the settings that trust a project."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr

from app.core.config import AppEnv
from app.core.errors import AppError, ErrorCode
from app.core.security.principal import MFA_METHOD
from app.modules.identity.adapters.firebase import (
    IDENTITY_TOOLKIT_SCOPE,
    FirebaseAccountCheck,
    FirebaseAdminDeleter,
    GoogleServiceAccount,
    firebase_issuer,
    firebase_project,
)
from app.modules.identity.adapters.idp_deletion import (
    CompositeDeleter,
    IdpDeletionError,
    build_idp_deleter,
)
from app.modules.identity.adapters.oidc import IssuerConfig, OidcVerifier, StaticKeyProvider
from app.modules.identity.config import FIREBASE_JWKS_URI, IdentitySettings
from tests.conftest import make_identity_settings

PROJECT = "travel-buddy-test"
ISSUER = firebase_issuer(PROJECT)
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
SERVICE_ACCOUNT = json.dumps(
    {
        "type": "service_account",
        "project_id": PROJECT,
        "private_key_id": "key-1",
        "private_key": PEM,
        "client_email": f"firebase-adminsdk@{PROJECT}.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
)


def _token(**firebase: Any) -> str:
    now = int(datetime.now(tz=UTC).timestamp())
    claims: dict[str, Any] = {
        "iss": ISSUER,
        "aud": PROJECT,
        "sub": "fb-uid-1",
        "user_id": "fb-uid-1",
        "iat": now,
        "exp": now + 3600,
        "auth_time": now - 30,
        "email": "Ana@Example.com",
        "email_verified": True,
        "name": "Ana Souza",
        "firebase": {"identities": {"email": ["ana@example.com"]}, **firebase},
    }
    return jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": "fb-1"})


class _Check:
    def __init__(self, result: datetime | None = None, error: AppError | None = None) -> None:
        self.result, self.error = result, error
        self.seen: list[str] = []

    async def credentials_valid_since(self, id_token: str) -> datetime | None:
        self.seen.append(id_token)
        if self.error is not None:
            raise self.error
        return self.result


def _verifier(check: _Check | None = None) -> OidcVerifier:
    return OidcVerifier(
        [
            IssuerConfig(
                issuer=ISSUER,
                audiences=[PROJECT],
                algorithms=["RS256"],
                keys=StaticKeyProvider({"fb-1": KEY.public_key()}),
                method="oidc",
                account_check=check,
            )
        ]
    )


# ─────────────────────────────── claims ───────────────────────────────


async def test_firebase_password_token_is_mapped() -> None:
    identity = await _verifier().verify(_token(sign_in_provider="password"), expected_nonce=None)
    assert identity.issuer == ISSUER
    assert identity.subject == "fb-uid-1"
    assert identity.email == "ana@example.com"
    assert identity.email_verified is True
    assert identity.name == "Ana Souza"
    assert identity.method == "email_password"
    assert identity.amr == frozenset({"pwd"})
    assert identity.recovered_at is None


@pytest.mark.parametrize(
    ("provider", "method"),
    [("google.com", "google"), ("apple.com", "apple"), ("phone", "oidc")],
)
async def test_firebase_sign_in_provider_sets_the_method(provider: str, method: str) -> None:
    identity = await _verifier().verify(_token(sign_in_provider=provider), expected_nonce=None)
    assert identity.method == method
    assert provider in identity.amr


@pytest.mark.req("ADM-007")
async def test_firebase_second_factor_counts_as_mfa() -> None:
    token = _token(sign_in_provider="password", sign_in_second_factor="totp")
    identity = await _verifier().verify(token, expected_nonce=None)
    assert MFA_METHOD in identity.amr
    plain = await _verifier().verify(_token(sign_in_provider="password"), expected_nonce=None)
    assert MFA_METHOD not in plain.amr


@pytest.mark.security
async def test_firebase_anonymous_sign_in_is_refused() -> None:
    with pytest.raises(AppError) as caught:
        await _verifier().verify(_token(sign_in_provider="anonymous"), expected_nonce=None)
    assert caught.value.code == ErrorCode.TOKEN_INVALID


async def test_unverified_firebase_email_is_reported_as_unverified() -> None:
    now = int(datetime.now(tz=UTC).timestamp())
    claims = {
        "iss": ISSUER,
        "aud": PROJECT,
        "sub": "fb-uid-2",
        "iat": now,
        "exp": now + 3600,
        "email": "new@example.com",
        "email_verified": False,
        "firebase": {"sign_in_provider": "password"},
    }
    token = jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": "fb-1"})
    identity = await _verifier().verify(token, expected_nonce=None)
    assert identity.email_verified is False


# ─────────────────────────────── account check (AUTH-005) ───────────────────────────────


@pytest.mark.req("AUTH-005")
async def test_valid_since_from_the_account_check_becomes_the_recovery_time() -> None:
    since = datetime(2026, 11, 10, 9, 30, tzinfo=UTC)
    check = _Check(result=since)
    token = _token(sign_in_provider="password")
    identity = await _verifier(check).verify(token, expected_nonce=None)
    assert identity.recovered_at == since
    assert check.seen == [token]


@pytest.mark.security
async def test_a_revoked_firebase_token_cannot_sign_in() -> None:
    check = _Check(error=AppError(ErrorCode.TOKEN_INVALID, "revoked"))
    with pytest.raises(AppError) as caught:
        await _verifier(check).verify(_token(sign_in_provider="password"), expected_nonce=None)
    assert caught.value.code == ErrorCode.TOKEN_INVALID


async def test_an_invalid_signature_never_reaches_the_account_check() -> None:
    check = _Check()
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(datetime.now(tz=UTC).timestamp())
    forged = jwt.encode(
        {"iss": ISSUER, "aud": PROJECT, "sub": "x", "iat": now, "exp": now + 60},
        other,
        algorithm="RS256",
        headers={"kid": "fb-1"},
    )
    with pytest.raises(AppError):
        await _verifier(check).verify(forged, expected_nonce=None)
    assert check.seen == []


def _lookup(handler: Any) -> FirebaseAccountCheck:
    return FirebaseAccountCheck("AIza-test-key", httpx.AsyncClient(transport=handler))


async def test_account_lookup_reports_valid_since() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"users": [{"localId": "u", "validSince": "1762767000"}]})

    since = await _lookup(httpx.MockTransport(respond)).credentials_valid_since("id-token")
    assert since == datetime.fromtimestamp(1762767000, tz=UTC)
    assert seen[0].url.path == "/v1/accounts:lookup"
    assert seen[0].url.params["key"] == "AIza-test-key"
    assert json.loads(seen[0].content) == {"idToken": "id-token"}


@pytest.mark.security
@pytest.mark.parametrize(
    "message",
    ["USER_DISABLED", "TOKEN_EXPIRED", "USER_NOT_FOUND", "CREDENTIAL_TOO_OLD_LOGIN_AGAIN"],
)
async def test_account_lookup_refuses_revoked_tokens_and_disabled_accounts(message: str) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": 400, "message": message}})

    with pytest.raises(AppError) as caught:
        await _lookup(httpx.MockTransport(respond)).credentials_valid_since("id-token")
    assert caught.value.code == ErrorCode.TOKEN_INVALID


@pytest.mark.security
async def test_account_lookup_refuses_a_disabled_flag() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"users": [{"validSince": "1", "disabled": True}]})

    with pytest.raises(AppError):
        await _lookup(httpx.MockTransport(respond)).credentials_valid_since("id-token")


async def test_account_lookup_outage_does_not_block_sign_in() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    def unavailable(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": {"message": "UNAVAILABLE"}})

    def odd(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"users": []})

    for handler in (broken, unavailable, odd):
        assert await _lookup(httpx.MockTransport(handler)).credentials_valid_since("t") is None


# ─────────────────────────────── account deletion (AUTH-010) ───────────────────────────────


def _admin(
    delete_status: int, delete_body: dict[str, Any], seen: list[httpx.Request]
) -> tuple[FirebaseAdminDeleter, httpx.AsyncClient]:
    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "ya29.test", "expires_in": 3600})
        return httpx.Response(delete_status, json=delete_body)

    http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    account = GoogleServiceAccount(SERVICE_ACCOUNT, http, scope=IDENTITY_TOOLKIT_SCOPE)
    return FirebaseAdminDeleter(PROJECT, account, http), http


@pytest.mark.req("AUTH-010")
async def test_firebase_account_is_deleted_with_a_service_account_token() -> None:
    seen: list[httpx.Request] = []
    deleter, _ = _admin(200, {}, seen)
    await deleter.delete(ISSUER, "fb-uid-1")
    await deleter.delete(ISSUER, "fb-uid-2")

    token_requests = [r for r in seen if r.url.host == "oauth2.googleapis.com"]
    assert len(token_requests) == 1  # the access token is cached
    form = parse_qs(token_requests[0].content.decode())
    assert form["grant_type"] == ["urn:ietf:params:oauth:grant-type:jwt-bearer"]
    assertion = jwt.decode(
        form["assertion"][0],
        KEY.public_key(),
        algorithms=["RS256"],
        audience="https://oauth2.googleapis.com/token",
    )
    assert assertion["iss"] == f"firebase-adminsdk@{PROJECT}.iam.gserviceaccount.com"
    assert assertion["scope"] == IDENTITY_TOOLKIT_SCOPE

    deletes = [r for r in seen if r.url.host == "identitytoolkit.googleapis.com"]
    assert [r.url.path for r in deletes] == [f"/v1/projects/{PROJECT}/accounts:delete"] * 2
    assert deletes[0].headers["authorization"] == "Bearer ya29.test"
    assert json.loads(deletes[0].content) == {"localId": "fb-uid-1"}


@pytest.mark.req("AUTH-010")
async def test_an_already_deleted_firebase_account_counts_as_deleted() -> None:
    deleter, _ = _admin(400, {"error": {"message": "USER_NOT_FOUND"}}, [])
    await deleter.delete(ISSUER, "gone")


@pytest.mark.req("AUTH-010")
async def test_firebase_deletion_failures_raise_to_retry() -> None:
    deleter, _ = _admin(500, {"error": {"message": "INTERNAL"}}, [])
    with pytest.raises(IdpDeletionError):
        await deleter.delete(ISSUER, "fb-uid-1")
    with pytest.raises(IdpDeletionError):
        await deleter.delete(firebase_issuer("someone-else"), "fb-uid-1")


def test_firebase_deleter_handles_only_its_project() -> None:
    deleter, _ = _admin(200, {}, [])
    assert deleter.handles(ISSUER)
    assert deleter.handles(ISSUER + "/")
    assert not deleter.handles(firebase_issuer("other-project"))
    assert not deleter.handles("https://abcd.supabase.co/auth/v1")
    assert firebase_project("https://securetoken.google.com/") is None


@pytest.mark.req("AUTH-010")
def test_idp_deleters_are_built_for_each_configured_provider() -> None:
    http = httpx.AsyncClient()
    firebase_only = build_idp_deleter(
        make_identity_settings(
            firebase_project_id=PROJECT,
            google_service_account_json=SecretStr(SERVICE_ACCOUNT),
        ),
        http,
    )
    assert isinstance(firebase_only, FirebaseAdminDeleter)
    both = build_idp_deleter(
        make_identity_settings(
            firebase_project_id=PROJECT,
            google_service_account_json=SecretStr(SERVICE_ACCOUNT),
            supabase_secret_key=SecretStr("sb_secret_x"),
        ),
        http,
    )
    assert isinstance(both, CompositeDeleter)
    assert both.handles(ISSUER)
    assert both.handles("https://abcd.supabase.co/auth/v1")
    assert not both.handles("https://accounts.google.com")
    # The project alone (no service account) cannot delete anything.
    assert build_idp_deleter(make_identity_settings(firebase_project_id=PROJECT), http) is None


# ─────────────────────────────── settings ───────────────────────────────


def test_a_firebase_project_is_a_trusted_issuer() -> None:
    settings = make_identity_settings(firebase_project_id=PROJECT)
    (issuer,) = settings.trusted_issuers
    assert issuer.issuer == ISSUER
    assert issuer.audiences == [PROJECT]
    assert str(issuer.jwks_uri) == FIREBASE_JWKS_URI
    assert issuer.algorithms == ["RS256"]
    assert make_identity_settings().trusted_issuers == []


def _production(**values: object) -> IdentitySettings:
    return IdentitySettings(  # type: ignore[call-arg]
        _env_file=None,
        app_env=AppEnv.PRODUCTION,
        refresh_token_derivation_key=SecretStr("x" * 40),
        **values,
    )


def test_production_accepts_firebase_instead_of_oidc_issuers() -> None:
    settings = _production(firebase_project_id=PROJECT, firebase_web_api_key="AIza-key")
    assert [i.issuer for i in settings.trusted_issuers] == [ISSUER]


@pytest.mark.security
def test_production_needs_the_web_api_key_for_the_account_check() -> None:
    with pytest.raises(ValueError, match="FIREBASE_WEB_API_KEY"):
        _production(firebase_project_id=PROJECT)
    with pytest.raises(ValueError, match="FIREBASE_PROJECT_ID or OIDC_ISSUERS"):
        _production()


@pytest.mark.parametrize("bad", ["Travel-Buddy", "ab", "-starts-with-dash", "x" * 31])
def test_firebase_project_id_is_validated(bad: str) -> None:
    with pytest.raises(ValueError):
        make_identity_settings(firebase_project_id=bad)
