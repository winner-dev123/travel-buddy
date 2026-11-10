"""Database engine/session management and declarative base with naming conventions."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from fastapi import Request
from sqlalchemy import CheckConstraint, MetaData, make_url, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

if TYPE_CHECKING:
    from app.core.config import Settings

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


CLOUD_SQL_SCOPE = "https://www.googleapis.com/auth/sqlservice.admin"


def cloud_sql_connect(
    instance: str, url: str, *, credentials_json: str | None
) -> tuple[Callable[[], Awaitable[Any]], Callable[[], Awaitable[None]]]:
    """``(connect, close)`` for Cloud SQL for PostgreSQL through the Cloud SQL Python Connector.

    The connector reaches the instance's public IP over TLS with an ephemeral certificate issued to
    the service account, so no IP allow-list is needed. That suits hosts without fixed egress
    addresses, such as Railway (ADR-0028). ``url`` supplies only the user, password and database
    name. The connector is created on first use, inside the running event loop, and certificates
    are refreshed lazily when a connection is opened. The import is deferred because the connector
    is the optional ``gcp`` extra.
    """
    parsed = make_url(url)
    state: dict[str, Any] = {}
    lock = asyncio.Lock()

    async def connector() -> Any:
        async with lock:
            if "connector" not in state:
                from google.cloud.sql.connector import create_async_connector

                credentials = None
                if credentials_json:
                    from google.oauth2 import service_account

                    credentials = service_account.Credentials.from_service_account_info(
                        json.loads(credentials_json), scopes=[CLOUD_SQL_SCOPE]
                    )
                state["connector"] = await create_async_connector(
                    credentials=credentials, refresh_strategy="lazy"
                )
        return state["connector"]

    async def connect() -> Any:
        return await (await connector()).connect_async(
            instance,
            "asyncpg",
            user=parsed.username,
            password=parsed.password,
            db=parsed.database,
        )

    async def close() -> None:
        if "connector" in state:
            await state.pop("connector").close_async()

    return connect, close


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
        cloud_sql_instance: str | None = None,
        google_credentials_json: str | None = None,
        echo: bool = False,
    ) -> None:
        engine_url, connect_args = engine_options(url, transaction_pooler=transaction_pooler)
        options: dict[str, Any] = {"connect_args": connect_args}
        self._close_connector: Callable[[], Awaitable[None]] | None = None
        if cloud_sql_instance:
            connect, self._close_connector = cloud_sql_connect(
                cloud_sql_instance, url, credentials_json=google_credentials_json
            )
            engine_url, options = "postgresql+asyncpg://", {"async_creator": connect}
        self.engine: AsyncEngine = create_async_engine(
            engine_url,
            pool_size=pool_size,
            max_overflow=pool_size if max_overflow is None else max_overflow,
            pool_pre_ping=True,
            # Managed poolers close idle server connections; recycle before they do.
            pool_recycle=pool_recycle_seconds,
            echo=echo,
            **options,
        )
        self.sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        url: str | None = None,
        pool_size: int | None = None,
        max_overflow: int | None = None,
    ) -> Database:
        """The database the settings describe: direct, pooled or Cloud SQL (ADR-0018, ADR-0028)."""
        credentials = settings.google_service_account_json
        return cls(
            url or settings.database_url,
            pool_size=settings.database_pool_size if pool_size is None else pool_size,
            max_overflow=settings.database_max_overflow if max_overflow is None else max_overflow,
            pool_recycle_seconds=settings.database_pool_recycle_seconds,
            transaction_pooler=settings.database_transaction_pooler,
            cloud_sql_instance=settings.database_cloud_sql_instance or None,
            google_credentials_json=credentials.get_secret_value() if credentials else None,
        )

    async def ping(self) -> None:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        await self.engine.dispose()
        if self._close_connector is not None:
            await self._close_connector()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session (unit of work) per request."""
    database: Database = request.app.state.database
    async with database.sessionmaker() as session:
        yield session
