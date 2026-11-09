"""Connection options for direct, session-pooled and transaction-pooled Postgres (ADR-0018)."""

from __future__ import annotations

from sqlalchemy import make_url

from app.core.db import SECURE_PUBLIC_SCHEMA_SQL, engine_options

SUPABASE_POOLER = (
    "postgresql+asyncpg://postgres.abcdefghijkl:s3cr%40t@aws-0-us-east-1.pooler.supabase.com"
    ":6543/postgres?ssl=require"
)


def test_direct_and_session_mode_are_untouched() -> None:
    url, connect_args = engine_options(SUPABASE_POOLER, transaction_pooler=False)
    assert url == SUPABASE_POOLER
    assert connect_args == {}


def test_transaction_pooler_disables_prepared_statement_caches() -> None:
    url, connect_args = engine_options(SUPABASE_POOLER, transaction_pooler=True)
    parsed = make_url(url)
    assert parsed.query["prepared_statement_cache_size"] == "0"
    assert parsed.query["ssl"] == "require"  # existing options preserved
    assert parsed.password == "s3cr@t"  # credentials preserved (URL-decoded)
    assert connect_args["statement_cache_size"] == 0
    name_func = connect_args["prepared_statement_name_func"]
    assert name_func() != name_func()  # unique statement names per pooled connection


def test_hardening_sql_covers_rls_and_supabase_api_roles() -> None:
    sql = SECURE_PUBLIC_SCHEMA_SQL
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FROM anon, authenticated" in sql
    assert "ALTER DEFAULT PRIVILEGES" in sql
    assert "REVOKE EXECUTE ON FUNCTION" in sql
