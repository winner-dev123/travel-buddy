"""OIDC ID-token verification against trusted issuers (threat T-AUTH-01).

* Issuer is read from the unverified token only to choose a verifier; everything is then
  re-verified with the issuer's keys: signature, ``iss``, ``aud``, ``exp``, ``iat`` skew, ``nonce``.
* Algorithms are pinned per issuer (no ``none``, no HMAC).
* JWKS are cached and refetched on an unknown ``kid`` at most once per minute.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
import jwt

from app.core.errors import AppError, ErrorCode
from app.core.security.principal import MFA_METHOD

_CLOCK_SKEW_SECONDS = 60


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    issuer: str
    subject: str
    email: str | None
    email_verified: bool
    name: str | None
    amr: frozenset[str]
    auth_time: datetime
    method: str
    # Since when the account's sessions are valid: the Supabase password-recovery link, or
    # Firebase's ``validSince`` (moved by a password change). Older sessions end (AUTH-005).
    recovered_at: datetime | None = None


class KeyProvider(Protocol):
    async def get_key(self, kid: str | None) -> Any: ...


class AccountCheck(Protocol):
    async def credentials_valid_since(self, id_token: str) -> datetime | None:
        """Called after the token verified: raises if the IdP says the token or account is no
        longer valid; returns since when the account's sessions are valid (None if unknown)."""
        ...


class StaticKeyProvider:
    """Keys known in-process (development IdP, tests)."""

    def __init__(self, keys: Mapping[str, Any]) -> None:
        self._keys = dict(keys)

    async def get_key(self, kid: str | None) -> Any:
        if kid is None or kid not in self._keys:
            raise _invalid("Unknown signing key.")
        return self._keys[kid]


class HttpJwksKeyProvider:
    """Fetches and caches an issuer's JWKS over HTTPS."""

    def __init__(
        self,
        jwks_uri: str,
        client: httpx.AsyncClient,
        *,
        ttl_seconds: float = 3600,
        min_refresh_seconds: float = 60,
    ) -> None:
        self._uri = jwks_uri
        self._client = client
        self._ttl = ttl_seconds
        self._min_refresh = min_refresh_seconds
        self._keys: dict[str, Any] = {}
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()

    async def _refresh(self) -> None:
        async with self._lock:
            if time.monotonic() - self._fetched_at < self._min_refresh and self._keys:
                return
            try:
                response = await self._client.get(self._uri, timeout=5.0)
                response.raise_for_status()
                jwk_set = jwt.PyJWKSet.from_dict(response.json())
            except (httpx.HTTPError, jwt.PyJWKSetError, ValueError) as exc:
                raise AppError(
                    ErrorCode.UPSTREAM_UNAVAILABLE, "Identity provider keys are unavailable."
                ) from exc
            self._keys = {k.key_id: k.key for k in jwk_set.keys if k.key_id}
            self._fetched_at = time.monotonic()

    async def get_key(self, kid: str | None) -> Any:
        stale = time.monotonic() - self._fetched_at > self._ttl
        if stale or kid not in self._keys:
            await self._refresh()
        if kid is None or kid not in self._keys:
            raise _invalid("Unknown signing key.")
        return self._keys[kid]


@dataclass(frozen=True, slots=True)
class IssuerConfig:
    issuer: str
    audiences: Sequence[str]
    algorithms: Sequence[str]
    keys: KeyProvider
    method: str
    account_check: AccountCheck | None = None


def _invalid(detail: str = "The identity token is invalid.") -> AppError:
    return AppError(ErrorCode.TOKEN_INVALID, detail)


def _parse_amr(claims: Mapping[str, Any]) -> frozenset[str]:
    """Authentication methods, normalized for platform policies (ADM-007, ADR-0020).

    RFC 8176 ``amr`` is a list of strings; Supabase Auth uses ``[{"method": ..., ...}]``.
    Supabase signals a completed second factor with ``aal: "aal2"`` and Firebase with
    ``firebase.sign_in_second_factor``; both are recorded as the RFC 8176 ``mfa`` method so
    policies need not know the vendor. Firebase's ``sign_in_provider`` is recorded too
    (``password`` as RFC 8176 ``pwd``).
    """
    value = claims.get("amr")
    methods: set[str] = set()
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                methods.add(item)
            elif isinstance(item, dict) and isinstance(item.get("method"), str):
                methods.add(item["method"])
    if claims.get("aal") == "aal2":
        methods.add(MFA_METHOD)
    firebase = _firebase_claims(claims)
    provider = firebase.get("sign_in_provider")
    if isinstance(provider, str):
        methods.add("pwd" if provider == "password" else provider)
    if isinstance(firebase.get("sign_in_second_factor"), str):
        methods.add(MFA_METHOD)
    return frozenset(methods)


def _firebase_claims(claims: Mapping[str, Any]) -> Mapping[str, Any]:
    value = claims.get("firebase")
    return value if isinstance(value, dict) else {}


# Firebase ``sign_in_provider`` → the identity method recorded with the account link (ADR-0028).
_FIREBASE_METHODS = {"password": "email_password", "google.com": "google", "apple.com": "apple"}


def _method(claims: Mapping[str, Any], default: str) -> str:
    provider = _firebase_claims(claims).get("sign_in_provider")
    return _FIREBASE_METHODS.get(provider, default) if isinstance(provider, str) else default


def _is_anonymous(claims: Mapping[str, Any]) -> bool:
    return (
        claims.get("is_anonymous") is True  # Supabase
        or _firebase_claims(claims).get("sign_in_provider") == "anonymous"  # Firebase
    )


RECOVERY_METHOD = "recovery"


def _recovered_at(claims: Mapping[str, Any]) -> datetime | None:
    """When the session behind the token was established through a password-recovery link.

    Supabase Auth records it as an ``amr`` entry ``{"method": "recovery", "timestamp": ...}``; the
    user is about to set (or has just set) a new password, so older sessions must end (AUTH-005).
    """
    stamps = [
        int(item["timestamp"])
        for item in claims.get("amr") or []
        if isinstance(item, dict)
        and item.get("method") == RECOVERY_METHOD
        and isinstance(item.get("timestamp"), int | float)
    ]
    return datetime.fromtimestamp(max(stamps), tz=UTC) if stamps else None


def _email_verified(claims: Mapping[str, Any]) -> bool:
    """Only a top-level, IdP-asserted ``email_verified: true`` counts.

    Supabase's ``user_metadata`` is writable by the user (``auth.updateUser({data})``), so
    ``user_metadata.email_verified`` is NOT trusted. For Supabase the top-level claim is added by
    the ``auth_hooks.custom_access_token`` hook from ``auth.users.email_confirmed_at``
    (migration 0003, ADR-0020); without the hook every email counts as unverified.
    """
    return claims.get("email_verified") is True


def _auth_time(claims: Mapping[str, Any]) -> int:
    """``auth_time`` if present; Supabase omits it but timestamps each ``amr`` entry instead.

    A refreshed Supabase token has a new ``iat`` while the user authenticated earlier, so the most
    recent ``amr`` timestamp is the better signal. ``iat`` is the last resort.
    """
    if isinstance(claims.get("auth_time"), int | float):
        return int(claims["auth_time"])
    stamps = [
        int(item["timestamp"])
        for item in claims.get("amr") or []
        if isinstance(item, dict) and isinstance(item.get("timestamp"), int | float)
    ]
    return max(stamps) if stamps else int(claims["iat"])


def _display_name(claims: Mapping[str, Any]) -> str | None:
    """Prefill for the profile display name (user-editable anyway, so metadata is fine here)."""
    candidates: list[Any] = [claims.get("name")]
    metadata = claims.get("user_metadata")
    if isinstance(metadata, dict):
        candidates += [metadata.get("full_name"), metadata.get("name")]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()[:100]
    return None


class OidcVerifier:
    def __init__(self, issuers: Sequence[IssuerConfig], *, now: Any = None) -> None:
        self._issuers = {cfg.issuer: cfg for cfg in issuers}
        self._now = now or (lambda: time.time())

    @property
    def issuers(self) -> frozenset[str]:
        return frozenset(self._issuers)

    async def verify(self, id_token: str, *, expected_nonce: str | None) -> VerifiedIdentity:
        try:
            header = jwt.get_unverified_header(id_token)
            unverified = jwt.decode(id_token, options={"verify_signature": False})
        except jwt.InvalidTokenError as exc:
            raise _invalid() from exc
        config = self._issuers.get(str(unverified.get("iss", "")))
        if config is None:
            raise _invalid("The identity token's issuer is not trusted.")
        if header.get("alg") not in config.algorithms:
            raise _invalid("The identity token uses a disallowed algorithm.")
        key = await config.keys.get_key(header.get("kid"))
        try:
            claims = jwt.decode(
                id_token,
                key,
                algorithms=list(config.algorithms),
                audience=list(config.audiences),
                issuer=config.issuer,
                leeway=_CLOCK_SKEW_SECONDS,
                options={"require": ["exp", "iat", "sub", "iss", "aud"], "verify_iat": False},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AppError(ErrorCode.TOKEN_EXPIRED, "The identity token has expired.") from exc
        except jwt.InvalidTokenError as exc:
            raise _invalid() from exc

        now = float(self._now())
        if float(claims["iat"]) > now + _CLOCK_SKEW_SECONDS:
            raise _invalid("The identity token was issued in the future.")
        if expected_nonce is not None and claims.get("nonce") != expected_nonce:
            raise _invalid("The identity token nonce does not match.")

        if _is_anonymous(claims):
            # Anonymous sign-ins are not accounts; never let them register or log in.
            raise _invalid("Anonymous sessions cannot be used to sign in.")
        recovered_at = _recovered_at(claims)
        if config.account_check is not None:
            # Firebase: refuses disabled accounts and revoked tokens. ``validSince`` moves when the
            # password changes, which ends older sessions like a Supabase recovery (AUTH-005).
            valid_since = await config.account_check.credentials_valid_since(id_token)
            if valid_since is not None:
                recovered_at = max(recovered_at or valid_since, valid_since)
        email = claims.get("email")
        amr = _parse_amr(claims)
        auth_time = datetime.fromtimestamp(_auth_time(claims), tz=UTC)
        return VerifiedIdentity(
            issuer=config.issuer,
            subject=str(claims["sub"]),
            email=str(email).strip().lower() if email else None,
            email_verified=_email_verified(claims),
            name=_display_name(claims),
            amr=amr,
            auth_time=auth_time,
            method=_method(claims, config.method),
            recovered_at=recovered_at,
        )
