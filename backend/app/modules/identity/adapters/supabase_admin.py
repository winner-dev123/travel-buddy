"""Supabase Auth Admin API: delete the IdP account at the end of the deletion saga (AUTH-010,
ADR-0020, BL-6.09).

Needs the project's secret key (``sb_secret_…``, or the legacy ``service_role`` JWT), which is
server-only. Without it the saga still erases our data and logs that the IdP account remains.
"""

from __future__ import annotations

from urllib.parse import quote

import httpx

from app.modules.identity.adapters.idp_deletion import IdpDeletionError


def supabase_base_url(issuer: str) -> str | None:
    """``https://<ref>.supabase.co/auth/v1`` → ``https://<ref>.supabase.co``."""
    trimmed = issuer.rstrip("/")
    if trimmed.endswith("/auth/v1") and ".supabase." in trimmed:
        return trimmed[: -len("/auth/v1")]
    return None


class SupabaseAdminDeleter:
    def __init__(self, secret_key: str, http: httpx.AsyncClient) -> None:
        self._key = secret_key
        self._http = http

    def handles(self, issuer: str) -> bool:
        return supabase_base_url(issuer) is not None

    async def delete(self, issuer: str, subject: str) -> None:
        base = supabase_base_url(issuer)
        if base is None:
            raise IdpDeletionError(f"not a Supabase issuer: {issuer}")
        headers = {"apikey": self._key}
        if self._key.count(".") == 2:  # legacy service_role JWT also goes in Authorization
            headers["Authorization"] = f"Bearer {self._key}"
        response = await self._http.delete(
            f"{base}/auth/v1/admin/users/{quote(subject, safe='')}", headers=headers, timeout=10
        )
        if response.status_code in (200, 204, 404):
            return
        raise IdpDeletionError(f"Supabase Admin API answered {response.status_code}")
