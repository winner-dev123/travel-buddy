"""Supabase Auth: custom access token hook asserting ``email_verified`` (ADR-0020).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-09

Supabase access tokens carry no trustworthy ``email_verified`` claim: the copy inside
``user_metadata`` is writable by the user. This hook adds a top-level ``email_verified`` computed
from ``auth.users.email_confirmed_at``, which only Supabase Auth sets.

It is created only where Supabase Auth exists (schema ``auth`` with ``auth.users`` and role
``supabase_auth_admin``). On plain PostgreSQL (local, CI) the migration is a no-op. After applying it
on Supabase, enable it in the dashboard: Authentication → Auth Hooks → "Customize Access Token
(JWT) Claims" → Postgres → schema ``auth_hooks``, function ``custom_access_token``.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The function body runs as ``supabase_auth_admin`` (SECURITY INVOKER), the role that owns
# ``auth.users``. Only that role may execute it; nobody else can even see into the schema.
UPGRADE_SQL = """
DO $migration$
BEGIN
    IF to_regclass('auth.users') IS NULL
       OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'supabase_auth_admin') THEN
        RAISE NOTICE 'Supabase Auth not present; skipping access token hook';
        RETURN;
    END IF;

    CREATE SCHEMA IF NOT EXISTS auth_hooks;
    REVOKE ALL ON SCHEMA auth_hooks FROM PUBLIC;

    EXECUTE $fn$
        CREATE OR REPLACE FUNCTION auth_hooks.custom_access_token(event jsonb)
        RETURNS jsonb
        LANGUAGE plpgsql
        STABLE
        SET search_path = ''
        AS $body$
        DECLARE
            claims jsonb := coalesce(event -> 'claims', '{}'::jsonb);
            confirmed boolean;
        BEGIN
            SELECT u.email IS NOT NULL AND u.email_confirmed_at IS NOT NULL
              INTO confirmed
              FROM auth.users AS u
             WHERE u.id = (event ->> 'user_id')::uuid;
            claims := jsonb_set(claims, '{email_verified}', to_jsonb(coalesce(confirmed, false)));
            RETURN jsonb_set(event, '{claims}', claims);
        END
        $body$
    $fn$;

    REVOKE ALL ON FUNCTION auth_hooks.custom_access_token(jsonb) FROM PUBLIC;
    GRANT USAGE ON SCHEMA auth_hooks TO supabase_auth_admin;
    GRANT EXECUTE ON FUNCTION auth_hooks.custom_access_token(jsonb) TO supabase_auth_admin;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON FUNCTION auth_hooks.custom_access_token(jsonb) FROM anon;
        REVOKE ALL ON SCHEMA auth_hooks FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON FUNCTION auth_hooks.custom_access_token(jsonb) FROM authenticated;
        REVOKE ALL ON SCHEMA auth_hooks FROM authenticated;
    END IF;
END
$migration$;
"""

DOWNGRADE_SQL = "DROP SCHEMA IF EXISTS auth_hooks CASCADE;"


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    # Disable the hook in the Supabase dashboard first, or token issuance fails while it points at
    # a missing function.
    op.execute(DOWNGRADE_SQL)
