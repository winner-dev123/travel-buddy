"""Static consistency between SQLAlchemy models and the baseline migration.

The authoritative comparison (autogenerate diff against a real database) runs in
tests/integration/test_migrations.py; this cheap check catches drift without a database.
"""

from __future__ import annotations

import re

import pytest

from app.models_registry import Base
from app.modules.observability.models import ActorType
from app.modules.platform.models import IdempotencyStatus, JobStatus
from tests.conftest import BACKEND_ROOT

BASELINE = BACKEND_ROOT / "migrations" / "versions" / "20261109_0001_baseline.py"


def _migration_text() -> str:
    return BASELINE.read_text(encoding="utf-8")


def test_metadata_contains_phase0_tables() -> None:
    assert set(Base.metadata.tables) == {
        "outbox_events",
        "asynchronous_jobs",
        "idempotency_keys",
        "audit_logs",
    }


def test_migration_creates_every_model_table() -> None:
    created = set(re.findall(r'op\.create_table\(\s*"([a-z_]+)"', _migration_text()))
    assert created == set(Base.metadata.tables)


@pytest.mark.parametrize(
    ("enum_cls", "constraint"),
    [
        (JobStatus, "ck_asynchronous_jobs__status_enum"),
        (IdempotencyStatus, "ck_idempotency_keys__status_enum"),
        (ActorType, "ck_audit_logs__actor_type_enum"),
    ],
)
def test_enum_check_constraints_match_python_enums(enum_cls: type, constraint: str) -> None:
    text = _migration_text()
    match = re.search(rf'"([^"]+)",\s*name="{constraint}"', text)
    assert match, f"{constraint} missing from migration"
    literals = set(re.findall(r"'([a-z_]+)'", match.group(1)))
    assert literals == {member.value for member in enum_cls}


@pytest.mark.req("SAFE-007")
def test_migration_enforces_append_only_audit_log() -> None:
    text = _migration_text()
    assert "BEFORE UPDATE OR DELETE ON audit_logs" in text
    assert "BEFORE TRUNCATE ON audit_logs" in text
