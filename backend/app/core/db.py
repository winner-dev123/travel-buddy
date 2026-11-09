"""Database engine/session management and declarative base with naming conventions."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterable
from enum import StrEnum
from typing import Any

from fastapi import Request
from sqlalchemy import CheckConstraint, MetaData, make_url, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

# Stable constraint names so Alembic autogenerate output is deterministic (ADR-0007).
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(table_name)s__%(column_0_N_name)s",
    "uq": "uq_%(table_name)s__%(column_0_N_name)s",
    "ck": "ck_%(table_name)s__%(constraint_name)s",
    "fk": "fk_%(table_name)s__%(column_0_N_name)s__%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    # Fetch server-generated values (now(), defaults) via RETURNING on INSERT/UPDATE so reading
    # them afterwards never triggers a lazy load, which is illegal under asyncio.
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012


def enum_check(column: str, values: Iterable[str] | type[StrEnum], name: str) -> CheckConstraint:
    """``text`` + CHECK enum constraint mirroring a Python StrEnum (ADR-0007)."""
    members = [v.value for v in values] if isinstance(values, type) else list(values)
    if not members:
        raise ValueError("enum_check requires at least one value")
    for member in members:
        if "'" in member:
            raise ValueError(f"invalid enum literal: {member!r}")
    allowed = ", ".join(f"'{m}'" for m in members)
    return CheckConstraint(f"{column} IN ({allowed})", name=name)


# Idempotent hardening applied after every migration run (migrations/env.py) and after test schema
# creation (ADR-0018, threat T-OPS-08).
#
# Supabase publishes the `public` schema through its auto-generated Data API (PostgREST) to the
# `anon` and `authenticated` roles. The backend is the only legitimate data path, so:
#   * every table we own in `public` gets Row Level Security with NO policies (deny-all for
#     non-owners; the backend connects as the table owner, which bypasses RLS);
#   * where the Supabase API roles exist, their table/sequence privileges are revoked, including
#     default privileges for future objects;
#   * EXECUTE on our own functions is revoked from PUBLIC (PostgREST exposes functions as RPC).
# On plain PostgreSQL (CI, local) the Supabase-specific statements are skipped.
SECURE_PUBLIC_SCHEMA_SQL = """
DO $hardening$
DECLARE
    obj record;
BEGIN
    FOR obj IN
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind IN ('r', 'p')
          AND c.relowner = current_user::regrole
          AND NOT c.relrowsecurity
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', obj.relname);
    END LOOP;

    FOR obj IN
        SELECT p.oid::regprocedure AS signature
        FROM pg_proc p
        WHERE p.pronamespace = 'public'::regnamespace
          AND p.proowner = current_user::regrole
    LOOP
        EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC', obj.signature);
    END LOOP;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
        REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
        REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM anon, authenticated;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            REVOKE EXECUTE ON FUNCTIONS FROM anon, authenticated;
    END IF;
END
$hardening$;
"""


def engine_options(url: str, *, transaction_pooler: bool) -> tuple[str, dict[str, Any]]:
    """Connection URL and connect_args for direct, session-pooled or transaction-pooled Postgres.

    Transaction poolers (Supabase Supavisor port 6543, PgBouncer transaction mode) hand each
    transaction to an arbitrary server connection, so asyncpg's prepared-statement caches must be
    disabled and statement names made unique (ADR-0018).
    """
    if not transaction_pooler:
        return url, {}
    pooled = make_url(url).update_query_dict({"prepared_statement_cache_size": "0"})
    connect_args: dict[str, Any] = {
        "statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4()}__",
    }
    return pooled.render_as_string(hide_password=False), connect_args


class Database:
    """Owns the async engine. Connections are opened lazily on first use."""

    def __init__(
        self,
        url: str,
        *,
        pool_size: int = 10,
        max_overflow: int | None = None,
        pool_recycle_seconds: int = 600,
        transaction_pooler: bool = False,
        echo: bool = False,
    ) -> None:
        engine_url, connect_args = engine_options(url, transaction_pooler=transaction_pooler)
        self.engine: AsyncEngine = create_async_engine(
            engine_url,
            pool_size=pool_size,
            max_overflow=pool_size if max_overflow is None else max_overflow,
            pool_pre_ping=True,
            # Managed poolers close idle server connections; recycle before they do.
            pool_recycle=pool_recycle_seconds,
            connect_args=connect_args,
            echo=echo,
        )
        self.sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    async def ping(self) -> None:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        await self.engine.dispose()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session (unit of work) per request."""
    database: Database = request.app.state.database
    async with database.sessionmaker() as session:
        yield session
