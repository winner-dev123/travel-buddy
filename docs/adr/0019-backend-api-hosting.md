# ADR-0019: Backend API hosting: Vercel serverless now, container host later

- **Status:** Superseded by [ADR-0028](0028-firebase-platform-and-railway-hosting.md) (cutover pending; in force until then)
- **Date:** 2026-11-09
- **Deciders:** Product owner, backend
- **Resolves:** the rest of PRD Q-8 for the staging API. Web is on Vercel (web workstream), and the database is on Supabase (ADR-0018)

## Context

The product owner asked to host the backend on Render. A Render service, even on the Free plan, requires a credit card on file in the owner's personal workspace, and the owner chose not to add one. The other Render workspace with billing is a shared team workspace belonging to another project. The owner asked for another free host instead. The owner's Vercel account already hosts the web app, has access to the repository, and needs no card on the Hobby plan.

## Decision

**Live staging API:** https://travel-buddy-api-jet.vercel.app (Vercel project `travel-buddy-api`). The unsuffixed `travel-buddy-api.vercel.app` belongs to another account.


* **Staging API on Vercel serverless functions** (Python runtime), as a separate Vercel project with root directory `backend`, in region `iad1` (Washington, D.C.), next to Supabase `us-east-1`.
  * Entry point: `backend/index.py` (`app = create_app()`). Routing: `backend/vercel.json`. Pinned dependencies: `backend/requirements.txt`. The bundle excludes tests and migrations (`.vercelignore`).
  * `APP_ENV=staging`: the production guards are active, the development IdP is refused, and API docs are hidden.
  * Database through the Supabase **transaction pooler** (port 6543, `DATABASE_TRANSACTION_POOLER=true`, pools of 2+3 per instance), which suits short-lived serverless instances. `READINESS_TIMEOUT_SECONDS=5` covers cold connections.
  * Trusted identity provider: Supabase Auth of the same project (`OIDC_ISSUERS`, ES256 JWKS).
  * Migrations run as a one-off (`alembic upgrade head` against the session pooler), never from the function.
* **Render stays ready as the container host**: [`render.yaml`](../../render.yaml) plus the Docker image (`$PORT`-aware) can deploy the same backend as soon as a card is on file. Long-running roles that serverless cannot host go there or to another container host:
  * the realtime WebSocket gateway (Phase 3);
  * workers and the scheduler (docs/02 §3).

## Consequences

* No cost and no card for staging. Deploys run on every push to `main`.
* Serverless limits: no WebSockets and no background processes in the function. Cold starts add latency to the first request. Vercel Hobby is intended for non-commercial use, so production needs Vercel Pro or the container host.
* Two deployment descriptors (Vercel and Render/Docker) must stay in sync. Both build from the same code and settings, and `requirements.txt` pins the runtime subset of `pyproject.toml`.
