# ADR-0018: Supabase as the managed PostgreSQL provider

- **Status:** Accepted. Superseded by [ADR-0028](0028-firebase-platform-and-railway-hosting.md), then reinstated by [ADR-0029](0029-supabase-free-tier-for-data-and-media.md) (cost)
- **Date:** 2026-11-09
- **Deciders:** Product owner (instruction: "use Supabase as the database"), backend
- **Requirements:** NFR-003, NFR-004, NFR-006, SAFE-010
- **Partially resolves:** PRD Q-8 (cloud provider, for the database tier)
- **Amended by:** [ADR-0020](0020-supabase-auth-identity-provider.md) (Supabase Auth is the IdP; the publishable key may be used for Auth endpoints only)

## Context

The architecture assumes PostgreSQL 16+ with PostGIS, `citext`, `pg_trgm` and `unaccent`, hosted as a managed service (docs/11). The product owner chose **Supabase**: project `dmvhbgxxxilcniadoqvb`, region `us-east-1` (East US, North Virginia), currently on the Free plan (Nano compute), with an upgrade to a paid plan planned as usage grows.

Supabase is managed PostgreSQL plus optional products (Auth, Data API/PostgREST, Storage, Realtime, Edge Functions). Two Supabase behaviours matter for us:

1. **The Data API exposes the `public` schema** to the `anon` and `authenticated` roles. Anyone holding the public anon key can reach every table that lacks Row Level Security, bypassing our backend and all its authorization.
2. **Networking**: on the Free plan the direct database host is IPv6-only. IPv4 clients connect through the Supavisor pooler: session mode on port 5432, transaction mode on port 6543.

## Decision

* **Use Supabase for the database only.** The backend stays the only data path. We keep our own platform sessions (ADR-0003), realtime gateway (doc 06), outbox and job queue (ADR-0004), and storage plan. Supabase Auth, Storage and Realtime are *options* evaluated separately: Supabase Auth could be configured as an OIDC issuer for Q-1 without changing our session design.
* **Connections**: `DATABASE_URL` points at the Supavisor **session pooler** (IPv4, prepared statements supported) with `?ssl=require`, for both the API and migrations. The transaction pooler is supported via `DATABASE_TRANSACTION_POOLER=true`, which disables asyncpg prepared-statement caching and randomizes statement names. Pool sizes are kept within plan limits (Free/Nano: 60 connections in total). Use `DATABASE_POOL_SIZE=5` and `DATABASE_MAX_OVERFLOW=5` per process.
* **Data API lockdown**, enforced automatically by `SECURE_PUBLIC_SCHEMA_SQL` (in `app/core/db.py`). It runs at the end of every Alembic run and after test schema creation:
  * Row Level Security is enabled with **no policies** on every table we own in `public`. That denies all non-owners; the backend connects as the owner, which bypasses RLS.
  * `anon` and `authenticated` lose all table, sequence and function privileges, including default privileges for future objects.
  * EXECUTE on our own functions is revoked from PUBLIC, because PostgREST exposes functions as RPC.
  * Operational complement: in the Supabase dashboard, **disable the Data API** (or remove `public` from the exposed schemas). Never distribute the `service_role` key. Our clients do not use the anon key. *(Amended by ADR-0020: clients may use the publishable key for Supabase Auth endpoints only, with Realtime public channels and Storage closed.)*
* **Extensions** are installed into Supabase's `extensions` schema when it exists, otherwise into `public` (CI/local). `f_unaccent` resolves the schema dynamically.
* **Tests never touch Supabase.** Integration tests truncate and downgrade schemas. The fixtures refuse non-local hosts unless `TEST_DATABASE_ALLOW_REMOTE=1` is set for a disposable database.
* **Local development and CI** keep plain PostGIS (docker-compose and the CI service container). The Supabase CLI local stack is an optional alternative.

## Consequences

* No database operations burden: managed upgrades, monitoring, and backups on paid plans.
* **Free-plan constraints, acceptable for development only**: the project pauses after about a week of inactivity, the database is capped at 500 MB, and there are no backups or point-in-time recovery. **Before any real user data**, upgrade to Pro (daily backups) and add PITR to meet NFR-004 (RPO ≤ 5 min). Consider the IPv4 add-on for direct connections, a compute upgrade for connection headroom, and read replicas in Phase 6+.
* **Region**: `us-east-1` is far from the EU-first plan in docs/11 §9. EU users' personal data would be processed in the US under Supabase's DPA and Standard Contractual Clauses (SAFE-010 transfer assessment required). A project's region cannot be changed in place. If EU residency is wanted, create an EU project **before launch** and migrate while the data is still trivial.
* Supabase-specific settings live in configuration (`DATABASE_URL`, pool settings), so moving to another managed PostgreSQL remains a configuration change plus a data migration.

## Alternatives considered

* **AWS RDS / Cloud SQL / Azure Flexible Server** (docs/11 reference): more networking and ops work up front. Still viable later.
* **Using the Supabase Data API from clients directly**: rejected. It would duplicate authorization in RLS policies, bypass our domain services, rate limits and audit, and contradict the contract-first API (ADR-0002).
