# Travel Buddy backend

Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2 (async) · Alembic · PostgreSQL 16 + PostGIS · Redis.
It is a modular monolith ([ADR-0001](../docs/adr/0001-modular-monolith.md)): one codebase deployed as several process roles.

## Status

| Area | State |
|---|---|
| Kernel: settings with production guards, JSON logging with redaction, request IDs, RFC 9457 errors, UUIDv7, signed cursors, feature flags | ✅ Implemented and tested |
| Authorization primitives: `Principal`, platform RBAC, `Allow`/`Deny` decisions, bearer authentication | ✅ Implemented and tested |
| Entitlement evaluator and group premium status ([docs/07](../docs/07-subscription-entitlement-policy.md)) | ✅ Pure logic, tested. Every user is on the free plan until billing lands (Phase 3) |
| **Identity (Phase 1)**: `POST /v1/auth/register`, `/login`, `/refresh`, `/logout`, `GET /v1/users/me`, `GET`/`DELETE /v1/users/me/sessions`, development IdP (`/v1/dev/idp/*`) | ✅ Implemented. Integration-tested against PostgreSQL, responses validated against the contract |
| Health: `/health/live`, `/health/ready` | ✅ |
| Migrations: `0001` baseline (extensions, outbox, jobs, idempotency, append-only audit log), `0002` identity and profiles | ✅ Verified against models (autogenerate diff); full up/down runs in CI with PostGIS |
| Other domain endpoints | ⏳ Per backlog. Nothing is mocked or stubbed |
| Realtime gateway, workers, scheduler | ⏳ Phase 1/3 (documented in docs/02, not yet present) |

### Signing in locally (development IdP)

With `DEV_IDP_ENABLED=true` (development or test only):

```bash
# 1. Mint a development ID token
curl -s localhost:8000/v1/dev/idp/token -H 'content-type: application/json' \
  -d '{"sub": "dev-ana", "email": "ana@example.com", "name": "Ana Souza"}'
# 2. First time: register (the age gate and consent versions are enforced)
curl -s localhost:8000/v1/auth/register -H 'content-type: application/json' \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"id_token": "<id_token>", "client": "web", "birth_date": "1995-05-17",
       "accepted_terms_version": "2026-11-01", "accepted_privacy_version": "2026-11-01", "locale": "en"}'
# 3. Afterwards: POST /v1/auth/login {"id_token": "...", "client": "web"}
```

## Layout

```
app/
  core/            # kernel. Must not import app.modules
  modules/<domain>/  # api.py, schemas.py, service.py (public), domain.py, models.py, repository.py, events.py
  main.py          # API app factory
  models_registry.py  # imports all models for Alembic
migrations/        # Alembic (async env, URL from settings)
tests/
  unit/            # no network
  integration/     # needs TEST_DATABASE_URL (PostGIS) and TEST_REDIS_URL
  contract/        # contracts/openapi/openapi.yaml + contracts/realtime/*.schema.json
```

Module boundary rules are enforced by [tests/unit/test_architecture_boundaries.py](tests/unit/test_architecture_boundaries.py). A module may import another module only via its `service` or `events`, and only downward in the layer DAG.

## Local setup

```bash
# from repo root: start PostGIS, Redis, MinIO
docker compose up -d

cd backend
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env

alembic upgrade head
uvicorn app.main:create_app --factory --reload
# http://localhost:8000/health/ready · API docs (dev only): http://localhost:8000/v1/docs
```

## Supabase (production database)

The database is Supabase-managed PostgreSQL ([ADR-0018](../docs/adr/0018-supabase-managed-postgres.md)):

1. In the Supabase dashboard open **Connect → Session pooler** and copy the URI.
2. Put it in `backend/.env` as `DATABASE_URL`, with the scheme `postgresql+asyncpg://` and `?ssl=require` appended (see [.env.example](.env.example)). `.env` is git-ignored, so never commit the password.
3. Apply the schema: `alembic upgrade head`. Every run ends by enabling Row Level Security on all tables and revoking Supabase's `anon`/`authenticated` access, so the auto-generated Data API cannot reach our data.
4. Recommended: disable the Data API in the dashboard (**Project Settings → Data API**). The backend does not use it.

Never point `TEST_DATABASE_URL` at Supabase. Integration tests truncate tables, and the fixtures refuse non-local hosts.

## Quality gates (same as CI)

```bash
ruff check app tests migrations && ruff format --check app tests migrations
mypy                       # strict, app/
pytest                     # unit + contract; integration tests skip without TEST_* URLs
TEST_DATABASE_URL=postgresql+asyncpg://travelbuddy:travelbuddy@localhost:5432/travelbuddy_test \
TEST_REDIS_URL=redis://localhost:6379/15 pytest -m integration
```

Link tests to requirements with `@pytest.mark.req("FEED-001")`. `python ../scripts/trace_requirements.py` builds the traceability matrix.

## Configuration

Settings are typed and validated at boot ([app/core/config.py](app/core/config.py)). Outside `development`/`test`, boot **fails** if a development-only adapter is enabled or `CURSOR_SIGNING_KEY` is weak (threat T-AUTH-08). See [.env.example](.env.example).
