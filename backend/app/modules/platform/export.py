"""Personal-data export helper (BL-6.03; AUTH-011, SAFE-010).

Each module exports the rows it owns about a user through :func:`export_rows`, naming the table
and the condition; the data-export job (identity) zips the sections. Secrets never leave: binary
columns and columns whose names say hash, ciphertext, secret, token or password are dropped, on
top of whatever the module excludes.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Collection
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import LargeBinary, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

_SECRET_COLUMN = re.compile(r"hash|ciphertext|secret|token|password|webpush_", re.IGNORECASE)


def jsonable(value: Any) -> Any:
    """A JSON-friendly copy of a column value."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bytes | memoryview):
        return None
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [jsonable(v) for v in value]
    return value


async def export_rows(
    session: AsyncSession,
    model: Any,
    *conditions: ColumnElement[bool],
    exclude: Collection[str] = (),
) -> list[dict[str, Any]]:
    """Rows of ``model`` matching ``conditions`` as plain dicts, oldest first when the table has
    ``created_at``; secret-looking and binary columns are always left out."""
    table = model.__table__
    columns = [
        column
        for column in table.columns
        if column.name not in exclude
        and not _SECRET_COLUMN.search(column.name)
        and not isinstance(column.type, LargeBinary)
    ]
    query = select(*columns).where(*conditions)
    if "created_at" in table.c:
        query = query.order_by(table.c.created_at)
    rows = await session.execute(query)
    return [{key: jsonable(value) for key, value in row._mapping.items()} for row in rows]
