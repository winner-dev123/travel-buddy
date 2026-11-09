# Travel Buddy backend

Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2 (async) · Alembic · PostgreSQL 16 + PostGIS · Redis.
It is a modular monolith ([ADR-0001](../docs/adr/0001-modular-monolith.md)): one codebase deployed as several process roles.

## Status (Phase 0)

| Area | State |
|---|---|
| Kernel: settings with production guards, JSON logging with redaction, request IDs, RFC 9457 errors, UUIDv7, signed cursors, feature flags | ✅ Implemented and tested |
| Authorization primitives: `Principal`, platform RBAC, `Allow`/`Deny` decisions | ✅ Implemented and tested |
| Entitlement evaluator and group premium status ([docs/07](../docs/07-subscription-entitlement-policy.md)) | ✅ Pure logic, tested. Not yet wired to persistence or providers (Phase 3) |
| Health: `/health/live`, `/health/ready` | ✅ |
| Baseline migration: extensions, outbox, jobs, idempotency, append-only audit log | ✅ Static checks locally. DB tests run in CI |
| Domain endpoints (`/v1/...`) | ⏳ Phase 1+. Nothing is mocked or stubbed |
| Realtime gateway, workers, scheduler | ⏳ Phase 1/3 (documented in docs/02, not yet present) |

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
