"""Database hardening for Supabase's Data API exposure (ADR-0018, threat T-OPS-08).

Runs on both schema paths: real migrations (CI) and create_all + hardening (local).
"""

from __future__ import annotations

import pytest

from tests.integration.conftest import db_scalar

pytestmark = [pytest.mark.integration, pytest.mark.security]


def test_every_owned_public_table_has_row_level_security(schema_db_url: str) -> None:
    exposed = db_scalar(
        schema_db_url,
        """
        SELECT string_agg(c.relname, ', ' ORDER BY c.relname)
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
          AND c.relowner = current_user::regrole AND NOT c.relrowsecurity
        """,
    )
    assert exposed is None, f"tables without RLS: {exposed}"


def test_our_functions_are_not_executable_by_public(schema_db_url: str) -> None:
    callable_by_public = db_scalar(
        schema_db_url,
        """
        SELECT string_agg(p.proname, ', ')
        FROM pg_proc p
        WHERE p.pronamespace = 'public'::regnamespace
          AND p.proowner = current_user::regrole
          AND (p.proacl IS NULL OR array_to_string(p.proacl, ',') ~ '(^|,)=X')
        """,
    )
    assert callable_by_public is None, f"functions executable by PUBLIC: {callable_by_public}"


def test_backend_still_works_as_table_owner(schema_db_url: str) -> None:
    # RLS without policies denies non-owners only; the backend role owns the tables.
    assert db_scalar(schema_db_url, "SELECT count(*) FROM users") is not None
