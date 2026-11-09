"""Shared fixtures.

Unit tests never touch the network: the app is built with injected readiness checks and
unreachable database/redis URLs (engines connect lazily, so nothing is opened).
Integration tests read TEST_DATABASE_URL / TEST_REDIS_URL and are skipped when unset.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import AppEnv, Settings
from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]


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
    return create_app(settings, readiness_checks={"database": _ok, "redis": _ok})


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def test_database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set (integration test needs PostGIS)")
    return url


@pytest.fixture
def test_redis_url() -> str:
    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.skip("TEST_REDIS_URL not set (integration test needs Redis)")
    return url
