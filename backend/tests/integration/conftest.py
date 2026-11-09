"""Integration fixtures: a real PostgreSQL schema plus an app wired to it.

Schema preparation:
* With PostGIS available (CI service container): ``alembic upgrade head``, i.e. the real migrations.
* Without PostGIS (developer machines without it): ``Base.metadata.create_all`` for the
  non-spatial tables. Migration correctness is still verified by test_migrations.py in CI.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.db import SECURE_PUBLIC_SCHEMA_SQL
from app.core.time import FixedClock
from app.main import create_app
from app.models_registry import Base
from tests.conftest import (
    BACKEND_ROOT,
    ensure_local_test_database,
    make_identity_settings,
    make_settings,
)

_IDENTITY_ROOT_TABLE = "users"  # TRUNCATE ... CASCADE clears every user-owned table


def postgis_available(url: str) -> bool:
    async def check() -> bool:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                found = await conn.scalar(
                    text("SELECT 1 FROM pg_available_extensions WHERE name = 'postgis'")
                )
                return found is not None
        finally:
            await engine.dispose()

    return asyncio.run(check())


def _alembic_upgrade(url: str) -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")


def _create_all(url: str) -> None:
    async def create() -> None:
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                for extension in ("citext", "pg_trgm", "unaccent"):
                    await conn.execute(text(f"CREATE EXTENSION IF NOT EXISTS {extension}"))
                # Rebuild so the schema always matches the current models (create_all never
                # alters existing tables). Only ever runs against a local test database.
                await conn.run_sync(Base.metadata.drop_all)
                await conn.run_sync(Base.metadata.create_all)
                # Same hardening the migration environment applies after every run.
                await conn.execute(text(SECURE_PUBLIC_SCHEMA_SQL))
        finally:
            await engine.dispose()

    asyncio.run(create())


@pytest.fixture(scope="session")
def schema_db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set (integration tests need PostgreSQL)")
    ensure_local_test_database(url)
    if postgis_available(url):
        _alembic_upgrade(url)
    else:
        _create_all(url)
    return url


def _truncate_users(url: str) -> None:
    async def truncate() -> None:
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                await conn.execute(text(f"TRUNCATE {_IDENTITY_ROOT_TABLE} CASCADE"))
        finally:
            await engine.dispose()

    asyncio.run(truncate())


@dataclass
class LiveApp:
    client: TestClient
    clock: FixedClock
    db_url: str


@pytest.fixture
def live_app(schema_db_url: str) -> Iterator[LiveApp]:
    _truncate_users(schema_db_url)
    clock = FixedClock(datetime.now(tz=UTC).replace(microsecond=0))

    async def ok() -> bool:
        return True

    app = create_app(
        make_settings(database_url=schema_db_url, dev_idp_enabled=True),
        identity_settings=make_identity_settings(),
        readiness_checks={"db": ok},
        clock=clock,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield LiveApp(client=client, clock=clock, db_url=schema_db_url)


def db_scalar(url: str, sql: str, **params: object) -> object:
    async def run() -> object:
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                return await conn.scalar(text(sql), params)
        finally:
            await engine.dispose()

    return asyncio.run(run())
