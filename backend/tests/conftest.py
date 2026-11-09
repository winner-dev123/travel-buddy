"""Shared fixtures.

Unit tests never touch the network: the app is built with injected readiness checks and
unreachable database/redis URLs (engines connect lazily, so nothing is opened).
Integration tests read TEST_DATABASE_URL / TEST_REDIS_URL and are skipped when unset.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import AppEnv, Settings
from app.main import create_app
from app.modules.identity.config import IdentitySettings

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def ed25519_test_pem() -> str:
    """A freshly generated (per test run) Ed25519 private key in PKCS#8 PEM."""
    return (
        Ed25519PrivateKey.generate()
        .private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        .decode("ascii")
    )


def make_identity_settings(**overrides: object) -> IdentitySettings:
    values: dict[str, object] = {"app_env": AppEnv.TEST}
    values.update(overrides)
    return IdentitySettings(_env_file=None, **values)  # type: ignore[call-arg]


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": AppEnv.TEST,
        "log_json": False,
        "log_level": "WARNING",
        "database_url": "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused",
        "redis_url": "redis://127.0.0.1:1/0",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


async def _ok() -> bool:
    return True


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(
        settings,
        identity_settings=make_identity_settings(),
        readiness_checks={"database": _ok, "redis": _ok},
    )


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


_LOCAL_DB_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "postgres"})


def ensure_local_test_database(url: str) -> str:
    """Integration tests TRUNCATE and downgrade schemas: never run them against a remote database
    (e.g. the Supabase project) unless explicitly allowed."""
    from sqlalchemy import make_url

    host = make_url(url).host or ""
    if host not in _LOCAL_DB_HOSTS and os.environ.get("TEST_DATABASE_ALLOW_REMOTE") != "1":
        pytest.exit(
            f"Refusing destructive integration tests against remote database host {host!r}. "
            "Point TEST_DATABASE_URL at a local/CI database "
            "(or set TEST_DATABASE_ALLOW_REMOTE=1 for a disposable remote one).",
            returncode=2,
        )
    return url


@pytest.fixture
def test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set (integration test needs PostGIS)")
    return ensure_local_test_database(url)


@pytest.fixture
def test_redis_url() -> str:
    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.skip("TEST_REDIS_URL not set (integration test needs Redis)")
    return url
