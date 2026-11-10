"""Migrations against a real PostGIS database (runs in CI; skipped without TEST_DATABASE_URL).

These tests are synchronous because Alembic's async env.py calls ``asyncio.run`` itself.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.models_registry import Base
from tests.conftest import BACKEND_ROOT

pytestmark = pytest.mark.integration

# Diff kinds that indicate real model/migration drift. Index diffs are verified explicitly below
# because autogenerate cannot reliably compare partial/expression indexes.
_STRUCTURAL_DIFFS = {"add_table", "remove_table", "add_column", "remove_column"}


def _alembic_config(url: str) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def _run(url: str, statements: list[str]) -> list[Any]:
    async def go() -> list[Any]:
        engine = create_async_engine(url)
        try:
            async with engine.begin() as connection:
                results = []
                for statement in statements:
                    result = await connection.execute(text(statement))
                    results.append(result.fetchall() if result.returns_rows else None)
                return results
        finally:
            await engine.dispose()

    return asyncio.run(go())


@pytest.fixture
def migrated(test_database_url: str) -> str:
    from tests.integration.conftest import postgis_available

    if not postgis_available(test_database_url):
        pytest.skip("PostGIS not installed on this PostgreSQL (migration tests run in CI)")
    config = _alembic_config(test_database_url)
    command.upgrade(config, "head")
    return test_database_url


def _diffs(url: str) -> list[Any]:
    def compare(connection: Connection) -> list[Any]:
        context = MigrationContext.configure(
            connection,
            opts={
                "compare_type": True,
                "include_object": lambda obj, name, type_, reflected, compare_to: (
                    not (type_ == "table" and reflected and name not in Base.metadata.tables)
                ),
            },
        )
        return list(compare_metadata(context, Base.metadata))

    async def go() -> list[Any]:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(compare)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def _flatten(diffs: list[Any]) -> list[tuple[Any, ...]]:
    flat: list[tuple[Any, ...]] = []
    for diff in diffs:
        if isinstance(diff, list):  # column modifications are nested lists
            flat.extend(diff)
        else:
            flat.append(diff)
    return flat


def test_models_match_migrations(migrated: str) -> None:
    structural = [d for d in _flatten(_diffs(migrated)) if d[0] in _STRUCTURAL_DIFFS]
    assert not structural, structural


def test_required_extensions_and_indexes_exist(migrated: str) -> None:
    extensions, indexes = _run(
        migrated,
        [
            "SELECT extname FROM pg_extension",
            "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()",
        ],
    )
    assert {"postgis", "citext", "pg_trgm", "unaccent"} <= {row[0] for row in extensions}
    assert {
        "ix_outbox_events__unpublished",
        "ix_asynchronous_jobs__claimable",
        "uq_asynchronous_jobs__active_dedupe_key",
        "ix_idempotency_keys__expires_at",
        "ix_audit_logs__resource",
        "ix_audit_logs__actor",
        "uq_destinations__slug",
        "uq_destinations__sibling_segment",
        "ix_destinations__path",
        "ix_destination_localizations__name_trgm",
        "ix_destination_boundaries__boundary",
    } <= {row[0] for row in indexes}


def test_immutable_unaccent_wrapper(migrated: str) -> None:
    (rows,) = _run(migrated, ["SELECT f_unaccent('São Paulo, Zürich, Bogotá')"])
    assert rows[0][0] == "Sao Paulo, Zurich, Bogota"


@pytest.mark.req("SAFE-007")
def test_audit_log_is_append_only(migrated: str) -> None:
    _run(
        migrated,
        [
            "INSERT INTO audit_logs (id, actor_type, action, resource_type, resource_id) "
            "VALUES (gen_random_uuid(), 'system', 'test.append_only', 'test', 'x')"
        ],
    )
    for statement in (
        "UPDATE audit_logs SET action = 'tampered' WHERE action = 'test.append_only'",
        "DELETE FROM audit_logs WHERE action = 'test.append_only'",
        "TRUNCATE audit_logs",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            _run(migrated, [statement])


def test_job_status_check_constraint(migrated: str) -> None:
    with pytest.raises(DBAPIError, match="ck_asynchronous_jobs__status_enum"):
        _run(
            migrated,
            [
                "INSERT INTO asynchronous_jobs (id, queue, kind, status) "
                "VALUES (gen_random_uuid(), 'q', 'k', 'bogus')"
            ],
        )


def test_check_constraint_names_are_not_doubled(migrated: str) -> None:
    """BL-1.29: migration 0042 renames the ``ck_<table>__ck_<table>__...`` names that early
    migrations produced, so migrated databases carry the names the models declare."""
    (rows,) = _run(
        migrated,
        [
            "SELECT c.conname FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid "
            "WHERE t.relnamespace = current_schema()::regnamespace AND c.contype = 'c'"
        ],
    )
    doubled = sorted(name for (name,) in rows if name.startswith("ck_") and "__ck_" in name)
    assert doubled == []
    names = {name for (name,) in rows}
    assert {"ck_asynchronous_jobs__status_enum", "ck_comments__body_length"} <= names


def test_migrations_are_reversible(migrated: str) -> None:
    config = _alembic_config(migrated)
    command.downgrade(config, "base")
    (tables,) = _run(
        migrated,
        ["SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"],
    )
    assert not ({row[0] for row in tables} & set(Base.metadata.tables))
    command.upgrade(config, "head")
