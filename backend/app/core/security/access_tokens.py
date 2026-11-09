"""Platform access tokens: EdDSA-signed JWTs, 15 minutes (architecture section 8, ADR-0003).

Issued by the identity module after a verified IdP sign-in; verified here, in the kernel, so
every module can authenticate requests without importing ``identity``. Expiry is checked
against the injectable clock (not wall time inside PyJWT) so behaviour is deterministic in tests.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.errors import AppError, ErrorCode
from app.core.ids import uuid7
from app.core.time import Clock, SystemClock

ISSUER = "urn:travelbuddy:api"
AUDIENCE = "travelbuddy-platform"
ALGORITHM = "EdDSA"
_CLOCK_SKEW = timedelta(seconds=30)
_DEV_KEY_LABEL = b"travelbuddy-development-only-platform-access-token-key-v1"


def development_signing_key() -> Ed25519PrivateKey:
    """Deterministic Ed25519 key for development/test only.

    Used when PLATFORM_JWT_PRIVATE_KEY is unset; the settings guard makes that impossible outside
    development/test. Deterministic so tokens survive restarts and work across local processes.
    """
    return Ed25519PrivateKey.from_private_bytes(hashlib.sha256(_DEV_KEY_LABEL).digest())


def load_ed25519_private_key(pem: str) -> Ed25519PrivateKey:
    # Accept single-line values with literal backslash-n escapes, as entered in hosting dashboards.
    normalized = pem.strip().replace("\\n", "\n")
    key = serialization.load_pem_private_key(normalized.encode("utf-8"), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("PLATFORM_JWT_PRIVATE_KEY must be an Ed25519 private key")
    return key


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID
    roles: frozenset[str]
    amr: frozenset[str]
    auth_time: datetime
    email_verified: bool
    age_assured: bool
    issued_at: datetime
    expires_at: datetime
    token_id: str


def _invalid(detail: str = "The access token is invalid.") -> AppError:
    return AppError(ErrorCode.TOKEN_INVALID, detail, headers={"WWW-Authenticate": "Bearer"})


class AccessTokenService:
    def __init__(
        self,
        private_key: Ed25519PrivateKey,
        *,
        key_id: str,
        ttl: timedelta,
        clock: Clock | None = None,
    ) -> None:
        self._private_key = private_key
        self._public_key = private_key.public_key()
        self._key_id = key_id
        self._ttl = ttl
        self._clock = clock or SystemClock()

    @property
    def ttl(self) -> timedelta:
        return self._ttl

    def issue(
        self,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        roles: frozenset[str],
        amr: frozenset[str],
        auth_time: datetime,
        email_verified: bool,
        age_assured: bool,
    ) -> tuple[str, datetime]:
        now = self._clock.now()
        expires_at = now + self._ttl
        payload = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": str(user_id),
            "sid": str(session_id),
            "roles": sorted(roles),
            "amr": sorted(amr),
            "auth_time": int(auth_time.timestamp()),
            "ev": email_verified,
            "aa": age_assured,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": str(uuid7()),
        }
        token = jwt.encode(
            payload, self._private_key, algorithm=ALGORITHM, headers={"kid": self._key_id}
        )
        return token, expires_at

    def verify(self, token: str) -> AccessTokenClaims:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise _invalid() from exc
        if header.get("alg") != ALGORITHM or header.get("kid") != self._key_id:
            raise _invalid()
        try:
            claims = jwt.decode(
                token,
                self._public_key,
                algorithms=[ALGORITHM],
                audience=AUDIENCE,
                issuer=ISSUER,
                options={
                    "require": ["exp", "iat", "sub", "sid", "aud", "iss"],
                    "verify_exp": False,  # checked below against the injectable clock
                    "verify_iat": False,
                },
            )
            user_id = uuid.UUID(str(claims["sub"]))
            session_id = uuid.UUID(str(claims["sid"]))
            issued_at = datetime.fromtimestamp(int(claims["iat"]), tz=UTC)
            expires_at = datetime.fromtimestamp(int(claims["exp"]), tz=UTC)
            auth_time = datetime.fromtimestamp(int(claims.get("auth_time", claims["iat"])), tz=UTC)
        except (jwt.InvalidTokenError, KeyError, TypeError, ValueError) as exc:
            raise _invalid() from exc
        now = self._clock.now()
        if now >= expires_at + _CLOCK_SKEW:
            raise AppError(
                ErrorCode.TOKEN_EXPIRED,
                "The access token has expired. Refresh and retry.",
                headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
            )
        if issued_at > now + _CLOCK_SKEW:
            raise _invalid()
        return AccessTokenClaims(
            user_id=user_id,
            session_id=session_id,
            roles=frozenset(str(r) for r in claims.get("roles", [])),
            amr=frozenset(str(a) for a in claims.get("amr", [])),
            auth_time=auth_time,
            email_verified=bool(claims.get("ev", False)),
            age_assured=bool(claims.get("aa", False)),
            issued_at=issued_at,
            expires_at=expires_at,
            token_id=str(claims.get("jti", "")),
        )
