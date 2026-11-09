"""Static consistency between SQLAlchemy models and the Alembic migrations.

The authoritative comparison (autogenerate diff against a real database) runs in
tests/integration/test_migrations.py; these cheap checks catch drift without a database.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import CheckConstraint

from app.models_registry import Base
from tests.conftest import BACKEND_ROOT

VERSIONS = BACKEND_ROOT / "migrations" / "versions"


def _migrations() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(VERSIONS.glob("*.py")))


def _enum_checks() -> list[tuple[str, frozenset[str]]]:
    checks: list[tuple[str, frozenset[str]]] = []
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            if isinstance(constraint, CheckConstraint) and str(constraint.name).endswith("_enum"):
                literals = frozenset(re.findall(r"'([a-z_]+)'", str(constraint.sqltext)))
                checks.append((str(constraint.name), literals))  # already convention-expanded
    return checks


def test_migrations_create_every_model_table() -> None:
    created = set(re.findall(r'op\.create_table\(\s*"([a-z_]+)"', _migrations()))
    assert created == set(Base.metadata.tables)


@pytest.mark.parametrize(("name", "literals"), _enum_checks(), ids=lambda v: str(v)[:60])
def test_enum_check_constraints_match_python_enums(name: str, literals: frozenset[str]) -> None:
    text = _migrations()
    sql_string = re.search(rf'"([^"]+)",\s*name="{name}"', text)  # sa.CheckConstraint("...", name=)
    helper = re.search(rf'_check\(\s*"{name}",\s*"\w+",\s*\[([^\]]*)\]', text, re.DOTALL)
    if sql_string:
        found = frozenset(re.findall(r"'([a-z_]+)'", sql_string.group(1)))
    elif helper:
        found = frozenset(re.findall(r'"([a-z_]+)"', helper.group(1)))
    else:
        pytest.fail(f"{name} missing from migrations")
    assert found == literals


@pytest.mark.req("SAFE-007")
def test_migration_enforces_append_only_audit_log() -> None:
    text = _migrations()
    assert "BEFORE UPDATE OR DELETE ON audit_logs" in text
    assert "BEFORE TRUNCATE ON audit_logs" in text
