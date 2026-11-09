# ADR-0002: Contract-first REST API (OpenAPI 3.1) and shared conventions

- **Status:** Accepted
- **Date:** 2026-11-09

## Context
The mobile app, web app, admin console and backend are developed in parallel. The master prompt requires versioned REST + OpenAPI and "API definitions and shared schemas synchronized".

## Decision
* `contracts/openapi/openapi.yaml` is the **normative** contract, reviewed in PRs before implementation.
* The backend's FastAPI-generated schema is tested against the contract in CI: every implemented route must exist in the contract, and its response models must be compatible.
* Mobile and web TypeScript types are **generated** from the contract (openapi-typescript), never hand-written.
* Conventions ([architecture §5](../02-system-architecture.md#5-platform-wide-api-conventions)): `/v1` prefix, problem+json (RFC 9457) with stable `code`, cursor pagination envelope, `Idempotency-Key`, `If-Match`, `X-Request-ID`, IETF RateLimit headers, 404-over-403 where existence is sensitive.
* Realtime frames are specified separately as JSON Schema (`contracts/realtime/`).

## Consequences
* There is a single source of truth, and generated clients cannot drift.
* Contract edits come before code, which is slightly slower for spikes. Spikes may live behind feature flags with `x-experimental: true`.

## Alternatives considered
* **Code-first (FastAPI → OpenAPI)**: simpler, but client work would wait on backend implementation and contracts would drift silently.
* **GraphQL**: flexible reads, but caching, authorization per field, and rate limiting are harder. Not justified.
