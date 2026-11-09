# Travel Buddy

AI travel guide and social travel community (working name). It combines destination-centric social content, AI itinerary planning, opt-in companion discovery, messaging, premium travel groups with challenges, GPS audio guides and offline packs, on iOS, Android and the web.

> **Status: Phase 0 complete (draft for approval).** Architecture, contracts, data model, policies and the platform kernel exist. No user-facing features are live yet. Unfinished capabilities sit behind feature flags that default to off, and nothing is mocked as if it were production.

## Repository

| Path | What | Docs |
|---|---|---|
| [backend/](backend/) | Python 3.12 / FastAPI modular monolith, PostgreSQL + PostGIS, Redis | [backend/README.md](backend/README.md) |
| [mobile/](mobile/) | React Native (Expo SDK 58, TypeScript strict) | [mobile/README.md](mobile/README.md) |
| [contracts/](contracts/) | OpenAPI 3.1 REST contract + realtime JSON Schemas (normative) | [contracts/README.md](contracts/README.md) |
| [docs/](docs/) | PRD, architecture, ERD, API, realtime, entitlements, threat model, backlog, tests, infra, ADRs | [docs/README.md](docs/README.md) |
| [infra/](infra/) | Local Docker support, Terraform layout | [docs/11](docs/11-infrastructure-deployment.md) |
| [scripts/](scripts/) | Requirement traceability matrix | — |

### Web

| Path | What | Docs |
|---|---|---|
| [apps/web/](apps/web/) | Next.js 16 App Router: public SEO site, traveler web app and admin in one app (ADR-0010) | [docs/web](docs/web/README.md) |
| [packages/](packages/) | Shared TS packages: `domain-types` (generated from the OpenAPI contract), `api-client` (+ server-only mock adapter), `validation`, `i18n` (en, es, pt-BR, fr, de), `ui` (design tokens + primitives), `config` | [docs/web/01](docs/web/01-architecture.md) |

```bash
npm install && npm run dev   # http://localhost:3000, mock adapter + dev persona sign-in until BL-1.01 is live
npm run check                # lint + typecheck (all workspaces) + unit tests
```

Browsers never hold platform tokens; a BFF keeps them in sealed HTTP-only cookies (ADR-0011). Decisions: ADR-0009…0014. <!-- Web workstream: edit this section freely. -->

## Quick start

```bash
docker compose up -d                       # PostGIS, Redis, MinIO
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
cp .env.example .env && alembic upgrade head
uvicorn app.main:create_app --factory --reload   # http://localhost:8000/health/ready

cd ../mobile && npm install && npm start   # Expo dev server
```

## Quality gates

| Area | Command | CI |
|---|---|---|
| Backend | `ruff check`, `ruff format --check`, `mypy`, `pytest` | `.github/workflows/ci-backend.yml` |
| Mobile | `npm run typecheck`, `npm run lint`, `npm run test:ci` | `.github/workflows/ci-mobile.yml` |
| Web | `npm run check`, `npm run gen:types:check`, `npm run build`, Playwright + axe | `.github/workflows/ci-web.yml` |
| Secrets | gitleaks | `.github/workflows/ci-security.yml` |
| Traceability | `python scripts/trace_requirements.py --enforce-phases 0` | ci-backend |

## Principles

Privacy by construction: traveler discovery stores no coordinates. The backend is the only authority for permissions and entitlements. Safety tools are never paywalled. Contracts come before code. Every requirement traces to tests.
