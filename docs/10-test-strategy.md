# 10 — Test Strategy

| | |
|---|---|
| **Status** | Draft v1.0 — Phase 0 |
| **Principle** | Production readiness is **not** "it compiles". A feature is done when its acceptance criteria (PRD) pass as automated tests, its threats (threat model) have verifying tests, and its traces are in the matrix |

## 1. Test pyramid and ownership

| Level | Scope | Tooling | Where | Runs |
|---|---|---|---|---|
| **Unit** | Pure domain logic: state machines, policies, ranking, normalization, entitlement evaluation, cursor signing | pytest (backend), Jest (mobile) | `backend/tests/unit`, `mobile/src/**/__tests__` | Every push, < 60 s |
| **Integration** | Module service + real Postgres/PostGIS + Redis. Repositories, transactions, concurrency, geospatial queries | pytest + Docker services (CI) / docker-compose (local) | `backend/tests/integration` | Every push |
| **Contract** | OpenAPI validity. Implemented routes ⊆ contract. Response schemas match. Realtime frames validate against JSON Schemas. Mobile generated types compile | openapi-spec-validator, schemathesis (Phase 1+), jsonschema, openapi-typescript | `backend/tests/contract` | Every push |
| **Security** | Authorization negative paths, enumeration, leakage, bypasses (threat register "S" items) | pytest (marked `security`) | `backend/tests/security` | Every push |
| **End-to-end** | User journeys across mobile + API + realtime | Maestro (mobile flows) against an ephemeral environment with dev adapters | `e2e/` | Nightly + pre-release |
| **Performance** | Feed, discovery, chat fanout, uploads, sync, AI throughput | k6 (HTTP + WebSocket) | `perf/` | Nightly on staging, pre-release |
| **Accessibility** | Contrast, labels, dynamic type | Jest a11y checks, manual VoiceOver/TalkBack passes | mobile | Per release |

## 2. Requirement traceability

* Backend: `@pytest.mark.req("FEED-001", "LOC-002")` on tests. The marker is registered in `conftest.py`, and unknown IDs fail collection once the PRD index is generated.
* Mobile: a `/* req: I18N-001 */` comment in test files.
* `python scripts/trace_requirements.py` parses PRD IDs and scans test markers. It emits `reports/traceability.md` (requirement → tests) and lists **Must** requirements of completed phases that have no test. CI fails if a completed-phase Must requirement is untraced.

## 3. Required tests by domain (from master prompt §23, mapped)

### 3.1 Unit

| Area | Cases | Req |
|---|---|---|
| Feed filtering and ranking | Weight application, recency half-life, destination-match tiers, author cap, duplicate suppression, negative feedback, deterministic tie-break | FEED-006, FEED-020 |
| Subscription permissions | Free/premium feature matrix, grant activity boundaries, quota math | BILL-007 |
| Group premium policy | Active / grace / lapsed / refund (no grace). Safety actions always allowed | GRP-009 |
| Connection state transitions | All valid transitions. Invalid ones raise. Block supersedes. Cooldown | CONN-001, CONN-006 |
| Group role authorization | Role × permission matrix. Rank rule for assignment | GRP-007, T-GRP-05 |
| Challenge answer evaluation | Normalization (case, accents, punctuation, whitespace, articles per language), multiple answers, attempt limits, cooldown | CHAL-005, CHAL-006 |
| Pricing / entitlement rules | Product → entitlement mapping, content purchase grants | BILL-001 |
| Kernel | Problem details shape, request ID validation, cursor tamper and expiry, UUIDv7 ordering | NFR-011 |

### 3.2 Integration

| Area | Cases |
|---|---|
| Authentication | ID token verification with a local JWKS; refresh rotation; reuse detection revokes family |
| Geospatial | Point → destination resolution across hierarchy; ancestor fan-out feed queries; `ST_DWithin` places |
| Group creation | Entitlement gate; owner membership + chat created atomically |
| Invitations | Concurrent redemption never exceeds `max_uses` or capacity; expiry; revoke |
| Messaging persistence | Seq monotonic under concurrent senders; idempotent `client_message_id`; sync after gap |
| Subscription events | Apple/Google notification fixtures → state machine; duplicates ignored; out-of-order guarded |
| Prize fulfillment | State transitions, audit rows, invalid transitions rejected |

### 3.3 End-to-end journeys

| Journey | Requirements |
|---|---|
| Registration → location-based feed (non-empty, destination-relevant) | PROF-002, FEED-001 |
| Discovery → connection request → accepted | DISC-*, CONN-002 |
| Connection → direct messaging (realtime + offline catch-up) | DM-001, DM-006 |
| Premium purchase (sandbox / dev billing) → group creation | GRP-001, BILL-003 |
| Group invitation → group chat | GRP-005, GCHAT-001 |
| Challenge publication → answer submission → result | CHAL-003, CHAL-011 |
| Offline destination download → airplane mode → playback | OFF-001, OFF-002 |

### 3.4 Security suite (must exist before each feature ships)

| Test | Threat |
|---|---|
| Unauthorized message access (IDOR by ID, by seq range, via attachments) | T-AZ-01, T-MSG-04 |
| Cross-group data leakage (REST + realtime after removal) | T-AZ-02, T-AZ-03 |
| Subscription bypass (client flags, forged receipts, shared receipts) | T-BILL-01..03 |
| Location enumeration (destination hopping limits, no distances, no coordinates in any response) | T-LOC-01..03 |
| Invitation token reuse / race / expiry | T-GRP-02 |
| Rate-limit enforcement on sensitive routes | T-MSG-03, CONN-005 |
| Injection and attachment handling (SQLi probes via schemathesis, oversized and polyglot files) | T-INJ-*, T-MED-* |
| Response-schema leakage scan: walk every OpenAPI response schema for forbidden field names (`lat`, `lng`, `latitude`, `longitude`, `distance`, `email` outside `MyProfile`, `birth_*`, `answer*` outside judge schemas) | T-LOC-01, T-CHAL-01 |
| Route coverage both ways, read from the app's generated OpenAPI document (FastAPI 0.16x wraps included routers, so `app.routes` lists no `APIRoute`s): every implemented route exists in the contract with its rate-limit class, and every contract operation of a delivered phase is implemented, except gaps listed explicitly in the test | ADR-0002 |

### 3.5 Performance targets (k6)

| Scenario | Load | Pass criteria |
|---|---|---|
| Feed pagination | 500 RPS mixed tabs, 10 pages deep | p95 < 300 ms, error < 0.1 % |
| Geospatial discovery | 100 RPS across 10 destinations | p95 < 250 ms |
| Concurrent chat delivery | 20 k sockets, 2 k msgs/s | p95 delivery < 500 ms, zero loss (seq audit) |
| Media uploads | 50 concurrent 5 MB uploads | Finalize → ready p95 < 10 s |
| Offline sync | 1 k clients reconciling 50 changes | No lost updates; conflicts surfaced |
| AI throughput | 20 concurrent generations | Quota, circuit breaker and timeouts behave correctly |

## 4. Test data and environments

| Environment | Purpose | Adapters |
|---|---|---|
| Local | Developer loop | docker-compose. Dev IdP, dev billing, fake push (logs), local MinIO, stub AI (marked development-only) |
| CI | Every push | Service containers (PostGIS, Redis). Same dev adapters |
| Ephemeral preview | Per PR (Phase 1+) | Full stack, seeded destinations |
| Staging | Release candidates | Real sandbox integrations (Apple/Google sandbox, IdP test tenant, AI provider with low quota) |
| Production | — | Real adapters only. Boot check refuses dev adapters |

Seed data: launch destinations with simplified boundaries, synthetic users and posts generated by factories (`factory_boy`). **No production data in non-production environments.**

## 5. CI quality gates

| Gate | Threshold |
|---|---|
| ruff lint + format check | 0 errors |
| mypy `--strict` | 0 errors |
| Module boundaries (`test_architecture_boundaries.py`) | 0 violations |
| pytest unit + integration + security + contract | 100 % pass |
| Coverage | ≥ 80 % backend overall. ≥ 90 % for `domain.py` and `entitlements.py` files |
| OpenAPI + realtime schema validation | Valid |
| Mobile: tsc, ESLint, Jest | 0 errors / 100 % pass |
| gitleaks secret scan | 0 findings |
| pip-audit / npm audit (high+) | 0 unwaived |
| Traceability | No untraced Must requirements for completed phases (from Phase 1 completion) |

## 6. Definition of Done (per backlog item)

1. Acceptance criteria automated, with requirement IDs on the tests.
2. Authorization negative tests present.
3. OpenAPI updated and the contract test green.
4. Migration (if any) reversible, with retention documented.
5. Feature flag for anything user-visible and incomplete.
6. Docs updated (PRD status, ADR if a decision was made).
7. Report: completed functionality, known gaps, remaining work.
