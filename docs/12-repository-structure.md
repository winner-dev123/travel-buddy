# 12 — Initial Repository Structure

| | |
|---|---|
| **Status** | v1.0 — Phase 0 (reflects what exists on disk) |
| **Related** | [ADR-0001](adr/0001-modular-monolith.md) · [ADR-0009](adr/0009-web-monorepo-layout.md) · [ADR-0015](adr/0015-expo-react-native.md) · [Web 01 §3](web/01-architecture.md) |

## 1. Top level

```
.
├── backend/                 # Python modular monolith (API, later realtime/worker/scheduler)
├── mobile/                  # Expo React Native app (standalone npm project; → apps/mobile in BL-0.20)
├── admin/                   # Staff console: React + Vite static app on its own origin (standalone npm project; ADR-0032)
├── apps/web/                # Next.js public site and traveller web app (web workstream; npm workspace)
├── packages/                # Shared TS packages (web workstream; platform-neutral ones reusable by mobile)
├── contracts/
│   ├── openapi/openapi.yaml # Normative REST contract (ADR-0002)
│   └── realtime/            # JSON Schemas for WebSocket frames
├── docs/                    # PRD, architecture, ERD, policies, threat model, backlog, ADRs
│   ├── adr/                 # Architecture decision records (append-only index)
│   └── web/                 # Web workstream docs
├── infra/
│   ├── docker/              # Local container support (Postgres init scripts)
│   └── terraform/           # Cloud-neutral module layout (docs/11 §4)
├── scripts/                 # Repo tooling (traceability matrix, …)
├── .github/workflows/       # ci-backend, ci-mobile, ci-admin, ci-security (+ ci-web by web workstream)
├── docker-compose.yml       # Local PostGIS, Redis, MinIO (+ optional API profile)
├── package.json             # npm workspaces root: apps/*, packages/* (web workstream)
└── README.md
```

## 2. Ownership (parallel workstreams)

| Path | Owner | Rule |
|---|---|---|
| `backend/`, `contracts/`, `infra/`, `mobile/`, `admin/`, `docs/01–17`, `docker-compose.yml`, `ci-backend.yml`, `ci-mobile.yml`, `ci-admin.yml`, `ci-security.yml`, root `README.md` | Backend/mobile workstream | Others request changes |
| `apps/web/`, `packages/*`, root `package.json`/lockfile/ESLint/Prettier/tsconfig, `docs/web/*`, `ci-web.yml` | Web workstream | Others request changes |
| `.gitignore`, `docs/adr/README.md` | Shared | Append only |

Contract changes go through `contracts/` first. Both clients regenerate types from it.

## 3. Backend

```
backend/
├── app/
│   ├── core/                    # kernel (no domain imports)
│   │   ├── config.py            # typed settings + production guards
│   │   ├── logging.py           # JSON logs, redaction
│   │   ├── middleware.py        # request ID, access log, security headers, 500 rendering
│   │   ├── errors.py            # RFC 9457 problems, ErrorCode
│   │   ├── pagination.py        # signed cursors, Page envelope
│   │   ├── feature_flags.py
│   │   ├── ids.py               # UUIDv7
│   │   ├── db.py · redis.py · time.py
│   │   └── security/            # Principal, RBAC, Allow/Deny policy decisions
│   ├── modules/
│   │   ├── billing/entitlements.py   # pure entitlement evaluator (Phase 0)
│   │   ├── health/api.py
│   │   ├── observability/models.py   # audit_logs
│   │   └── platform/models.py        # outbox, jobs, idempotency
│   ├── main.py                  # app factory
│   └── models_registry.py       # Alembic metadata import
├── migrations/                  # Alembic (0001 baseline)
├── tests/{unit,integration,contract}/
├── Dockerfile · pyproject.toml · alembic.ini · .env.example · README.md
```

New domain modules follow the per-module layout in [architecture §4.1](02-system-architecture.md#41-layout-and-layering) and must be registered in the layer map of the boundary test.

## 4. Mobile

```
mobile/
├── app/                 # Expo Router routes: (tabs)/, (auth)/, (onboarding)/
├── src/
│   ├── api/             # typed client, problem+json errors, pagination types, generated/ (from contract)
│   ├── auth/            # secure token store
│   ├── components/      # FeatureGate, OnlineOnlyBadge, …
│   ├── config/          # env, feature flags
│   ├── i18n/            # en, es, pt-BR, fr, de
│   ├── offline/         # connectivity
│   ├── state/           # Zustand stores
│   └── theme/           # tokens (light/dark), contrast utilities
├── __tests__/ · jest.setup.ts · eslint.config.js · tsconfig.json · app.json
```

Details: [mobile/README.md](../mobile/README.md) and [03 — Navigation and screens](03-mobile-navigation-and-screens.md).

## 5. Conventions

* Branching: trunk-based. Short-lived feature branches go to `main` via PR with required CI checks.
* Commits: Conventional Commits (`feat(feed): …`, `fix(billing): …`). The requirement ID goes in the body when one applies.
* Every PR runs the security checklist in [threat model §6](08-privacy-security-threat-model.md#6-security-requirements-checklist-per-pull-request).
* Requirement traceability: `python scripts/trace_requirements.py`.
