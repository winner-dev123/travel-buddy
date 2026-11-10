"""Every table that points at a user is either part of the personal-data export or left out for a
stated reason (BL-6.03; AUTH-011, SAFE-010). A new table with personal data fails here until its
module exports it (``export_user_data``) or it is listed below."""

from __future__ import annotations

import importlib
import inspect

import pytest

import app.models_registry  # noqa: F401 - registers every model
from app.core.db import Base

# Tables that reference users but are not exported, and why.
NOT_EXPORTED = {
    "idempotency_keys": "technical replay cache, kept 24 hours",
    "realtime_tickets": "single-use connection tickets, kept minutes",
    "feed_sessions": "ephemeral ranking sessions",
    "message_receipts": "delivery and read pointers derived from conversations",
    "message_mentions": "derived from the messages, which are exported",
    "conversation_pins": "shared conversation state set by any member",
    "moderation_actions": "staff decisions; subject access runs through support (SAFE-010)",
    "group_ownership_transfers": "short-lived offers; current ownership is in groups_owned",
    "challenge_teams": "team records; the member's team is in challenge_participations",
}


def _user_tables() -> dict[str, type]:
    tables: dict[str, type] = {}
    for mapper in Base.registry.mappers:
        table = mapper.local_table
        refs_user = table.name == "users" or any(
            fk.column.table.name == "users"
            for column in table.columns
            for fk in column.foreign_keys
        )
        if refs_user:
            tables[table.name] = mapper.class_
    return tables


@pytest.mark.req("AUTH-011", "SAFE-010")
def test_every_user_table_is_exported_or_excused() -> None:
    missing = []
    for name, model in sorted(_user_tables().items()):
        if name in NOT_EXPORTED:
            continue
        module = model.__module__.rsplit(".", 1)[0]  # app.modules.<module>
        service = importlib.import_module(f"{module}.service")
        exporter = getattr(service, "export_user_data", None)
        if exporter is None or model.__name__ not in inspect.getsource(exporter):
            missing.append(f"{name} ({model.__module__}.{model.__name__})")
    assert not missing, f"personal-data tables missing from the export: {missing}"


def test_excused_tables_still_exist() -> None:
    stale = set(NOT_EXPORTED) - set(_user_tables())
    assert not stale, f"remove these from NOT_EXPORTED: {sorted(stale)}"
