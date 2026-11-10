"""Supabase Auth Admin deletion adapter and the cache purge for deleted accounts (AUTH-010)."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from pydantic import SecretStr

from app.modules.identity.adapters.idp_deletion import IdpDeletionError, build_idp_deleter
from app.modules.identity.adapters.supabase_admin import SupabaseAdminDeleter, supabase_base_url
from app.modules.web_cache.domain import revalidation_for
from tests.conftest import make_identity_settings

pytestmark = pytest.mark.req("AUTH-010")

ISSUER = "https://abcd1234.supabase.co/auth/v1"


def test_supabase_base_url_is_derived_from_the_issuer() -> None:
    assert supabase_base_url(ISSUER) == "https://abcd1234.supabase.co"
    assert supabase_base_url(ISSUER + "/") == "https://abcd1234.supabase.co"
    assert supabase_base_url("https://accounts.google.com") is None
    assert supabase_base_url("http://localhost:8000/v1/dev/idp") is None


def _deleter(
    status: int, seen: list[httpx.Request], key: str = "sb_secret_abc"
) -> SupabaseAdminDeleter:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status)

    return SupabaseAdminDeleter(key, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize("status", [200, 204, 404])
def test_deleting_succeeds_or_is_already_done(status: int) -> None:
    seen: list[httpx.Request] = []
    asyncio.run(_deleter(status, seen).delete(ISSUER, "8b1e/odd id"))
    [request] = seen
    assert request.method == "DELETE"
    assert str(request.url) == "https://abcd1234.supabase.co/auth/v1/admin/users/8b1e%2Fodd%20id"
    assert request.headers["apikey"] == "sb_secret_abc"
    assert "authorization" not in request.headers  # new secret keys are not JWTs


def test_legacy_service_role_jwt_is_also_sent_as_bearer() -> None:
    seen: list[httpx.Request] = []
    asyncio.run(_deleter(200, seen, key="aaa.bbb.ccc").delete(ISSUER, "user-1"))
    assert seen[0].headers["authorization"] == "Bearer aaa.bbb.ccc"


@pytest.mark.parametrize("status", [401, 500, 503])
def test_failures_raise_so_the_job_retries(status: int) -> None:
    with pytest.raises(IdpDeletionError):
        asyncio.run(_deleter(status, []).delete(ISSUER, "user-1"))


def test_the_deleter_exists_only_with_a_secret_key() -> None:
    http = httpx.AsyncClient()
    assert build_idp_deleter(make_identity_settings(), http) is None
    configured = build_idp_deleter(
        make_identity_settings(supabase_secret_key=SecretStr("sb_secret_x")), http
    )
    assert configured is not None
    assert configured.handles(ISSUER)
    assert not configured.handles("https://accounts.google.com")


@pytest.mark.req("AUTH-010", "SAFE-012")
def test_deleted_accounts_purge_their_cached_pages() -> None:
    decision = revalidation_for("user.deleted", {"user_id": "x", "handle": "ana.travels"})
    assert decision is not None
    assert decision.reason == "profile_visibility_changed"
    assert decision.tags == ("profile:ana.travels", "stories", "sitemap")
