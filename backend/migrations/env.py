"""Alembic environment (async engine; URL from application settings)."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection

from app.core.config import get_settings
from app.core.db import SECURE_PUBLIC_SCHEMA_SQL, Database
from app.models_registry import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# PostGIS / extension-owned objects that autogenerate must ignore.
_IGNORED_TABLES = {"spatial_ref_sys"}


def _include_object(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    return not (type_ == "table" and name in _IGNORED_TABLES)


def _database_url() -> str:
    override = config.get_main_option("sqlalchemy.url")
    return override or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=_include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
        context.execute(SECURE_PUBLIC_SCHEMA_SQL)


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=_include_object,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
        # Every run ends by (re)applying RLS and Supabase API-role revocations (ADR-0018), so a
        # newly created table can never be left exposed through the Supabase Data API.
        context.execute(SECURE_PUBLIC_SCHEMA_SQL)


async def run_migrations_online() -> None:
    # Same connection path as the app: direct, pooled or Cloud SQL connector (ADR-0028).
    database = Database.from_settings(
        get_settings(), url=_database_url(), pool_size=1, max_overflow=0
    )
    try:
        async with database.engine.connect() as connection:
            await connection.run_sync(_do_run_migrations)
    finally:
        await database.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
