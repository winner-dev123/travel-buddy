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


class KeyProvider(Protocol):
    async def get_key(self, kid: str | None) -> Any: ...


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


def _invalid(detail: str = "The identity token is invalid.") -> AppError:
    return AppError(ErrorCode.TOKEN_INVALID, detail)


def _parse_amr(value: Any) -> frozenset[str]:
    """RFC 8176 ``amr`` is a list of strings; Supabase Auth uses ``[{"method": ..., ...}]``."""
    if not isinstance(value, list):
        return frozenset()
    methods: set[str] = set()
    for item in value:
        if isinstance(item, str):
            methods.add(item)
        elif isinstance(item, dict) and isinstance(item.get("method"), str):
            methods.add(item["method"])
    return frozenset(methods)


def _email_verified(claims: Mapping[str, Any]) -> bool:
    """Standard ``email_verified``; falls back to Supabase's ``user_metadata.email_verified``."""
    if "email_verified" in claims:
        return claims["email_verified"] is True
    metadata = claims.get("user_metadata")
    return isinstance(metadata, dict) and metadata.get("email_verified") is True


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

        if claims.get("is_anonymous") is True:
            # Supabase anonymous sign-ins are not accounts; never let them register or log in.
            raise _invalid("Anonymous sessions cannot be used to sign in.")
        email = claims.get("email")
        amr = _parse_amr(claims.get("amr"))
        auth_time = datetime.fromtimestamp(int(claims.get("auth_time", claims["iat"])), tz=UTC)
        return VerifiedIdentity(
            issuer=config.issuer,
            subject=str(claims["sub"]),
            email=str(email).strip().lower() if email else None,
            email_verified=_email_verified(claims),
            name=str(claims["name"]) if claims.get("name") else None,
            amr=amr,
            auth_time=auth_time,
            method=config.method,
        )
