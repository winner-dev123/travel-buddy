"""Migration 0003: Supabase custom access token hook (ADR-0020).

Supabase is simulated inside one transaction that is rolled back: roles, an ``auth.users`` table,
then the migration's SQL. PostgreSQL DDL and CREATE ROLE are transactional, so nothing leaks.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import uuid
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

pytestmark = [pytest.mark.integration, pytest.mark.security]

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "20261109_0003_supabase_access_token_hook.py"
)

_FAKE_SUPABASE = (
    """
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'supabase_auth_admin') THEN
            CREATE ROLE supabase_auth_admin NOLOGIN;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            CREATE ROLE anon NOLOGIN;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            CREATE ROLE authenticated NOLOGIN;
        END IF;
    END $$
    """,
    "CREATE SCHEMA auth",
    "CREATE TABLE auth.users (id uuid PRIMARY KEY, email text, email_confirmed_at timestamptz)",
    "GRANT USAGE ON SCHEMA auth TO supabase_auth_admin",
    "GRANT SELECT ON auth.users TO supabase_auth_admin",
)


def _migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0003", _MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(url: str, check: object) -> None:
    async def go() -> None:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    await check(conn)  # type: ignore[operator]
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(go())


async def _fake_supabase(conn: AsyncConnection) -> None:
    for statement in _FAKE_SUPABASE:
        await conn.execute(text(statement))


async def _hook(conn: AsyncConnection, user_id: uuid.UUID) -> dict[str, object]:
    event = {"user_id": str(user_id), "claims": {"sub": str(user_id), "aud": "authenticated"}}
    await conn.execute(text("SET LOCAL ROLE supabase_auth_admin"))
    result = await conn.scalar(
        text("SELECT auth_hooks.custom_access_token(CAST(:event AS jsonb))"),
        {"event": json.dumps(event)},
    )
    await conn.execute(text("RESET ROLE"))
    payload = result if isinstance(result, dict) else json.loads(str(result))
    claims = payload["claims"]
    assert isinstance(claims, dict)
    return claims


def test_hook_asserts_email_verified_from_auth_users(schema_db_url: str) -> None:
    migration = _migration()
    confirmed, unconfirmed, missing = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    async def check(conn: AsyncConnection) -> None:
        await _fake_supabase(conn)
        await conn.execute(text(migration.UPGRADE_SQL))
        await conn.execute(
            text(
                "INSERT INTO auth.users (id, email, email_confirmed_at) VALUES "
                "(:a, 'ana@example.com', now()), (:b, 'bo@example.com', NULL)"
            ),
            {"a": confirmed, "b": unconfirmed},
        )
        assert (await _hook(conn, confirmed))["email_verified"] is True
        assert (await _hook(conn, unconfirmed))["email_verified"] is False
        assert (await _hook(conn, missing))["email_verified"] is False
        # Other claims are preserved.
        assert (await _hook(conn, confirmed))["aud"] == "authenticated"

    _run(schema_db_url, check)


def test_only_supabase_auth_admin_can_execute_the_hook(schema_db_url: str) -> None:
    migration = _migration()

    async def check(conn: AsyncConnection) -> None:
        await _fake_supabase(conn)
        await conn.execute(text(migration.UPGRADE_SQL))
        signature = "auth_hooks.custom_access_token(jsonb)"
        for role, expected in (
            ("supabase_auth_admin", True),
            ("anon", False),
            ("authenticated", False),
        ):
            allowed = await conn.scalar(
                text("SELECT has_function_privilege(:role, :fn, 'EXECUTE')"),
                {"role": role, "fn": signature},
            )
            assert allowed is expected, role

    _run(schema_db_url, check)


def test_migration_is_a_no_op_without_supabase_auth(schema_db_url: str) -> None:
    migration = _migration()

    async def check(conn: AsyncConnection) -> None:
        await conn.execute(text(migration.UPGRADE_SQL))
        assert await conn.scalar(text("SELECT to_regnamespace('auth_hooks')")) is None

    _run(schema_db_url, check)
