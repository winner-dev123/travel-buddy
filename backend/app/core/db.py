"""Database engine/session management and declarative base with naming conventions."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from enum import StrEnum

from fastapi import Request
from sqlalchemy import CheckConstraint, MetaData, text
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


class Database:
    """Owns the async engine. Connections are opened lazily on first use."""

    def __init__(self, url: str, *, pool_size: int = 10, echo: bool = False) -> None:
        self.engine: AsyncEngine = create_async_engine(
            url,
            pool_size=pool_size,
            max_overflow=pool_size,
            pool_pre_ping=True,
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
