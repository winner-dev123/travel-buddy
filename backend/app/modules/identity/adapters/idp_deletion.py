"""Deleting the identity-provider account at the end of the deletion saga (AUTH-010).

One adapter per provider (Supabase Auth, Firebase Authentication); the job picks the adapter that
handles the account's issuer. Without credentials for a provider, our data is still erased and
the job logs that the IdP account remains.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

import httpx

from app.modules.identity.config import IdentitySettings


class IdpAccountDeleter(Protocol):
    def handles(self, issuer: str) -> bool: ...

    async def delete(self, issuer: str, subject: str) -> None:
        """Delete the account; an already-missing account counts as deleted. Raises to retry."""
        ...


class IdpDeletionError(Exception):
    pass


class CompositeDeleter:
    def __init__(self, deleters: Sequence[IdpAccountDeleter]) -> None:
        self._deleters = list(deleters)

    def handles(self, issuer: str) -> bool:
        return any(d.handles(issuer) for d in self._deleters)

    async def delete(self, issuer: str, subject: str) -> None:
        for deleter in self._deleters:
            if deleter.handles(issuer):
                await deleter.delete(issuer, subject)
                return
        raise IdpDeletionError(f"no deleter for issuer {issuer}")


def build_idp_deleter(
    settings: IdentitySettings, http: httpx.AsyncClient
) -> IdpAccountDeleter | None:
    from app.modules.identity.adapters.firebase import (
        IDENTITY_TOOLKIT_SCOPE,
        FirebaseAdminDeleter,
        GoogleServiceAccount,
    )
    from app.modules.identity.adapters.supabase_admin import SupabaseAdminDeleter

    deleters: list[IdpAccountDeleter] = []
    if settings.supabase_secret_key is not None:
        deleters.append(SupabaseAdminDeleter(settings.supabase_secret_key.get_secret_value(), http))
    if settings.firebase_project_id and settings.google_service_account_json is not None:
        account = GoogleServiceAccount(
            settings.google_service_account_json.get_secret_value(),
            http,
            scope=IDENTITY_TOOLKIT_SCOPE,
        )
        deleters.append(FirebaseAdminDeleter(settings.firebase_project_id, account, http))
    if not deleters:
        return None
    return deleters[0] if len(deleters) == 1 else CompositeDeleter(deleters)
