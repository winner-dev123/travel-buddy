"""Firebase Authentication as the identity provider (ADR-0028).

* ID tokens are ordinary OIDC JWTs: RS256, issuer ``https://securetoken.google.com/<project>``,
  audience ``<project>``, keys from Google's public JWKS. The generic verifier checks them and
  reads Firebase's claims (``adapters/oidc.py``).
* ``FirebaseAccountCheck`` asks Firebase about the account behind a verified token. It rejects
  tokens of disabled or deleted accounts and tokens revoked by a password change, and reports
  ``validSince``, the moment older sessions stopped being valid (AUTH-005).
* ``FirebaseAdminDeleter`` deletes the Firebase account at the end of the deletion saga
  (AUTH-010). It authenticates as a service account through the OAuth 2.0 JWT-bearer grant.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from urllib.parse import quote

import httpx
import jwt

from app.core.errors import AppError, ErrorCode
from app.modules.identity.adapters.idp_deletion import IdpDeletionError
from app.modules.identity.config import FIREBASE_ISSUER_PREFIX

logger = logging.getLogger(__name__)

IDENTITY_TOOLKIT = "https://identitytoolkit.googleapis.com/v1"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"  # noqa: S105 (a URL, not a secret)
IDENTITY_TOOLKIT_SCOPE = "https://www.googleapis.com/auth/identitytoolkit"

# accounts:lookup answers these for a token that must no longer sign anyone in.
_REVOKED = frozenset(
    {
        "INVALID_ID_TOKEN",
        "TOKEN_EXPIRED",
        "USER_NOT_FOUND",
        "USER_DISABLED",
        "CREDENTIAL_TOO_OLD_LOGIN_AGAIN",
    }
)


def firebase_issuer(project_id: str) -> str:
    return f"{FIREBASE_ISSUER_PREFIX}{project_id}"


def firebase_project(issuer: str) -> str | None:
    if issuer.startswith(FIREBASE_ISSUER_PREFIX):
        project = issuer[len(FIREBASE_ISSUER_PREFIX) :].strip("/")
        return project or None
    return None


def _error_message(response: httpx.Response) -> str:
    """Identity Toolkit errors look like ``{"error": {"message": "USER_DISABLED : detail"}}``."""
    try:
        error = response.json().get("error", {})
    except ValueError:
        return ""
    message = error.get("message") if isinstance(error, dict) else None
    return message.split(" ", 1)[0] if isinstance(message, str) else ""


class FirebaseAccountCheck:
    """Looks the account up with the user's own ID token and the project's Web API key.

    The Web API key only identifies the project and ships in every client, so it is not a secret.
    A lookup that cannot be completed (network, quota) is logged and skipped instead of blocking
    sign-in; Firebase's explicit "this token or account is no longer valid" answers are enforced.
    """

    def __init__(self, api_key: str, http: httpx.AsyncClient) -> None:
        self._key = api_key
        self._http = http

    async def credentials_valid_since(self, id_token: str) -> datetime | None:
        try:
            response = await self._http.post(
                f"{IDENTITY_TOOLKIT}/accounts:lookup",
                params={"key": self._key},
                json={"idToken": id_token},
                timeout=5.0,
            )
        except httpx.HTTPError as exc:
            logger.warning("firebase_lookup_unavailable", extra={"error": type(exc).__name__})
            return None
        if response.status_code == 400 and _error_message(response) in _REVOKED:
            raise AppError(ErrorCode.TOKEN_INVALID, "This sign-in is no longer valid.")
        if response.status_code != 200:
            logger.warning("firebase_lookup_failed", extra={"status": response.status_code})
            return None
        try:
            users = response.json().get("users") or []
            valid_since = int(users[0]["validSince"])
        except (ValueError, LookupError, TypeError, AttributeError):
            return None
        if users[0].get("disabled") is True:
            raise AppError(ErrorCode.TOKEN_INVALID, "This sign-in is no longer valid.")
        return datetime.fromtimestamp(valid_since, tz=UTC)


class GoogleServiceAccount:
    """OAuth 2.0 access tokens for a Google service account (RFC 7523 JWT-bearer grant)."""

    def __init__(self, key_json: str, http: httpx.AsyncClient, *, scope: str) -> None:
        info = json.loads(key_json)
        self.email: str = info["client_email"]
        self.project_id: str | None = info.get("project_id")
        self._private_key: str = info["private_key"]
        self._key_id: str | None = info.get("private_key_id")
        self._token_uri: str = info.get("token_uri") or GOOGLE_TOKEN_URI
        self._scope = scope
        self._http = http
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def access_token(self) -> str:
        async with self._lock:
            if self._token is not None and time.time() < self._expires_at - 60:
                return self._token
            now = int(time.time())
            assertion = jwt.encode(
                {
                    "iss": self.email,
                    "scope": self._scope,
                    "aud": self._token_uri,
                    "iat": now,
                    "exp": now + 3600,
                },
                self._private_key,
                algorithm="RS256",
                headers={"kid": self._key_id} if self._key_id else None,
            )
            response = await self._http.post(
                self._token_uri,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
                timeout=10,
            )
            if response.status_code != 200:
                raise RuntimeError(f"Google token endpoint answered {response.status_code}")
            body = response.json()
            self._token = str(body["access_token"])
            self._expires_at = now + float(body.get("expires_in", 3600))
            return self._token


class FirebaseAdminDeleter:
    """Deletes Firebase Authentication accounts of one project (AUTH-010)."""

    def __init__(self, project_id: str, account: GoogleServiceAccount, http: httpx.AsyncClient):
        self._project = project_id
        self._account = account
        self._http = http

    def handles(self, issuer: str) -> bool:
        return firebase_project(issuer) == self._project

    async def delete(self, issuer: str, subject: str) -> None:
        if not self.handles(issuer):
            raise IdpDeletionError(f"not this Firebase project: {issuer}")
        token = await self._account.access_token()
        response = await self._http.post(
            f"{IDENTITY_TOOLKIT}/projects/{quote(self._project, safe='')}/accounts:delete",
            headers={"Authorization": f"Bearer {token}"},
            json={"localId": subject},
            timeout=10,
        )
        if response.status_code == 200:
            return
        if response.status_code in (400, 404) and _error_message(response) == "USER_NOT_FOUND":
            return  # already gone
        raise IdpDeletionError(f"Firebase accounts:delete answered {response.status_code}")
