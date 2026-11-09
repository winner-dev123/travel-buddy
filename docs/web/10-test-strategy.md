# Web 10 — Web Test Strategy

| | |
|---|---|
| **Status** | Draft v1.0 — Web Phase 1 |
| **Owner** | QA automation (web) · Web engineering |
| **Extends** | [10 — Test strategy](../10-test-strategy.md) (normative: principles, traceability, environments, Definition of Done). This document adds the web layers (Vitest, Playwright, axe, Lighthouse CI) and the web E2E journeys. Backend tests stay owned by the backend stream |
| **Related** | [Web 03 §9](03-roles-permissions.md#9-test-obligations) · [Web 06](06-api-integration.md) · [Web 07 §10](07-seo-strategy.md#10-monitoring-and-governance) · [Web 08 §12](08-security-privacy.md#12-authorization-test-catalogue) · [Web 09 §13](09-backlog.md#13-web-definition-of-done) |

---

## 1. Principles (web-specific additions to doc 10)

1. **Test against the contract, not the implementation.** Unit and integration tests use the `@travelbuddy/api-client` mock transport or recorded fixtures that validate against the OpenAPI spec (once it exists). E2E runs against the mock in CI and against the live backend dev stack or staging for journeys the mock cannot honestly simulate.
2. **The mock never makes a journey "pass" that the platform cannot do.** Payments, AI and chat return `503 feature_not_available_in_mock` (01 §7.1). Journeys that need them run only against the backend dev stack (doc 10 §4 "Local": dev IdP, dev billing, stub AI) or staging.
3. **Authorization is tested from the outside.** Every behaviour code (03 §3) has a UI test, and every cross-user rule has a security test (§8).
4. **Accessibility and performance are gates, not reports.**

## 2. Pyramid, tools and ownership

| Level | Scope | Tooling | Location | Runs |
|---|---|---|---|---|
| **Unit** | Pure functions and hooks: validation schemas, API-client error mapping/retries/idempotency, cursor handling, query keys, session sealing, CSRF compare, `next` validation, URL safety, SEO builders (metadata, JSON-LD), formatters, permission-aware rendering helpers | Vitest 5 + jsdom | `packages/*/src/**/*.test.ts`, `apps/web/src/**/*.test.ts(x)` | Every push, < 60 s |
| **Component** | UI primitives and feature components with state (loading/empty/error/unauthorized), keyboard behaviour, optimistic updates and rollback | Vitest + React Testing Library + `@testing-library/user-event` + `vitest-axe` | next to components | Every push |
| **Integration (web server)** | Route handlers and proxy in-process: BFF proxy (CSRF, allow-lists, refresh, header stripping), `/api/auth/*` with the dev IdP, `proxy.ts` redirect matrix (02 §3), env boot guard, mock adapter contract behaviour | Vitest (node environment) calling handlers with `Request` objects | `apps/web/src/**/__tests__/*.int.test.ts` | Every push |
| **Contract** | Mock routes ⊆ OpenAPI paths; mock fixtures validate against spec schemas; generated types compile and match hand-written aliases; realtime frames used by the web validate against `contracts/realtime` schemas | `openapi-typescript`, Ajv (JSON Schema 2020-12) | `packages/api-client/src/mock/__contract__` | Every push (once the spec exists; skipped with a visible notice before) |
| **E2E** | User journeys in a real browser (§9), SEO checks (07 §10), security cases (08 §12 W rows) | Playwright 1.65 + `@axe-core/playwright` | `apps/web/e2e/` | PR (mock, Chromium), nightly (full matrix, live dev stack), pre-release (staging) |
| **Accessibility** | axe on every route state; keyboard paths; manual screen-reader passes | axe (component + E2E), manual NVDA/JAWS/VoiceOver/TalkBack | §6 | PR (automated), per release (manual) |
| **Performance** | Core Web Vitals lab budgets per route class, bundle-size budgets | Lighthouse CI, `@next/bundle-analyzer` + size check | §7 | PR (subset), nightly (full) |
| **Visual regression** | Key templates in both themes and 3 breakpoints | Playwright screenshots (later: hosted service) | §11 | From Phase 3, nightly |

## 3. Unit tests (minimum set)

| Area | Cases | Req / threat |
|---|---|---|
| `@travelbuddy/validation` | Field limits equal 06 shapes (display name 1–50, bio ≤ 300, handle regex, caption, tags ≤ 10, media ≤ 10); birth date → under-18 rejected client-side (server authoritative) | PROF-003, POST-009, AUTH-008 |
| API client | Problem → `ApiError` (incl. `entitlement`, `quota`, `resets_at`); non-problem bodies; network error → `network_error`; retries only for idempotent requests; **no retry on `quota_exceeded`**; `Retry-After` honoured; idempotency key reused across retries of one intent | 06 §6 |
| Pagination | `next_cursor` chaining; `page.reset` replaces pages; dedupe by ID across pages | FEED-004 |
| Session | Seal/unseal round-trip; tamper → null; wrong key → null; `kid` rotation accepts previous key; expiry handling | T-WEB-02 |
| CSRF | Constant-time compare; missing header; mismatched cookie; `Sec-Fetch-Site` cross-site rejected | T-WEB-03 |
| Redirect safety | `next` validation corpus (`//evil`, `/\evil`, `https://…`, encoded variants) | T-WEB-05 |
| URL safety | `safeUrl()` rejects `javascript:`, `data:`, `vbscript:`, mixed-case and whitespace tricks | T-WEB-13 |
| JSON-LD | Escaping of `<`, `>`, `&`, U+2028/9; builders emit valid schema for fixtures | 07 §5, T-WEB-10 |
| Metadata | Canonical and `hreflang` per route class (02 §2.6); `noindex` on filtered views | 07 §4 |
| Location | Rounding to 3 dp; coordinates excluded from query keys and persisted stores | T-WEB-23, LOC-003 |
| i18n | **Key parity** across en/es/pt-BR/fr/de; ICU messages compile; no hard-coded UI strings (lint rule) | I18N-001, NFR-014 |
| Permission helpers | Behaviour code per problem `code` (03 §3, 06 §8) | 03 |
| Env guard | Unsafe combinations throw (mock or dev IdP outside dev/test, short secret, missing map style in production) | T-WEB-08 |

## 4. Component and integration tests

| Feature | Component cases | Server integration cases |
|---|---|---|
| Auth pages | Provider buttons, register form (birth date, consent checkboxes with version links), error display for `age_restricted`, `account_suspended` | `/api/auth/dev` → cookies set, CSRF rotated; `/api/auth/callback` state mismatch → error page; logout clears cookies |
| Shell | Sidebar/bottom nav switch at breakpoints; active route; unread badges; discovery indicator | Layout redirects: no session → `/login?next=`; not onboarded → `/onboarding` |
| Feed | Tabs; skeleton → content → empty; error with request ID; context label per `source` (`gps`, `selected`, `upcoming_trip`, `interests`, `global`, `following`); optimistic reaction rollback on failure; "Load more" fallback | BFF passes `near` but logs redact it |
| Onboarding | Step navigation, skip, resume from draft, discovery default off | Completes via mock and lands on `/feed` |
| Composer | Validation, upload progress, `email_unverified` prompt, visibility selector | Presign → finalize → publish against the mock |
| Report / block | Reason list from the taxonomy; idempotent submit | — |
| Upsell / quota | `entitlement_required` vs `quota_exceeded` render differently | — |
| BFF | — | Allowed/blocked paths (08 A24); method allow-list; admin gate for non-staff (A16); refresh on `token_expired`; failed refresh → `401 session_expired` + cleared cookie; `Set-Cookie` from upstream stripped; `X-Request-ID` propagated; `Cache-Control: private, no-store` |
| Proxy | — | Redirect matrix (02 §3.1), locale prefixes, signed-in `/` → `/feed`, security headers and CSP profile per route class |

Component tests inject a fake `ApiClient` or the mock transport through providers, so no network is involved.

## 5. Contract tests

| Check | Detail |
|---|---|
| Spec ↔ types | `npm run contracts:generate`, then `git diff --exit-code packages/domain-types/src/generated.ts` |
| Mock ↔ spec paths | Every mock route (method + path template) exists in `openapi.yaml` |
| Mock ↔ spec schemas | Each mock fixture response validates against the operation's response schema (Ajv) |
| Leakage scan (web mirror of doc 10 §3.4) | Mock fixtures for "another user" types contain no `lat`, `lng`, `latitude`, `longitude`, `distance`, `email`, `birth_*`, `answer*` |
| Realtime | Fixture frames for the subset in 06 §5 validate against `contracts/realtime` schemas |

Until the spec exists, the job prints "contract checks skipped: contracts/openapi/openapi.yaml not found" and passes. It becomes required the day the file lands on `main`.

## 6. Accessibility

Target: **WCAG 2.2 AA** for all three experiences (NFR-008 extended to the public site and traveler web app).

| Layer | Practice |
|---|---|
| Automated | `vitest-axe` on component states; `@axe-core/playwright` on every E2E page visit (tags `wcag2a`, `wcag2aa`, `wcag21aa`, `wcag22aa`); **0 violations** gate (known false positives allow-listed with justification and expiry) |
| Keyboard | E2E keyboard-only passes for: navigation, destination search combobox, feed actions, composer, dialogs (focus trap and return), itinerary reordering alternative (WCAG 2.5.7), chat composer |
| Screen readers | Manual pass per release: NVDA + Firefox, JAWS + Chrome (admin), VoiceOver + Safari (macOS and iOS), TalkBack + Chrome (Android) on the 8 journeys |
| Visual | Contrast tokens checked in unit tests (01 §13 pairs); 200 % zoom and 320 px reflow on key templates; `prefers-reduced-motion` respected; focus indicators visible in both themes |
| Content | Alt text required on post media (composer prompts); captions/transcripts for audio tours where available; language of parts (`lang` on user content and fallback copy) |
| RTL readiness | Snapshot of key layouts with `dir="rtl"` (pseudo-locale) to catch physical CSS properties |

## 7. Performance

| Check | Tool | Budget source | Gate |
|---|---|---|---|
| Lab CWV (LCP, CLS, TBT as INP proxy) on home, directory, city page, story, feed (mock), messages shell | Lighthouse CI (mobile preset, 3 runs, median) | 01 §15 | PR: home + city + feed. Nightly: all |
| First-load JS per route | Next build output + size-limit script | 01 §15 (130 KB public, 200 KB app, gzip) | PR fails on regression above budget |
| Map, composer, assistant, player lazy-loaded | Bundle analyzer assertions (chunk not in initial route manifest) | 01 §15 | PR |
| Field CWV | RUM (`useReportWebVitals`) dashboards per route template and locale | 01 §15 p75 | Release review |
| Server load (BFF) | k6 scenario reusing doc 10 §3.5 feed pagination through the BFF | p95 BFF overhead < 50 ms over direct API | Pre-release on staging |

## 8. Security tests

Web-owned cases are the **W** rows of [08 §12](08-security-privacy.md#12-authorization-test-catalogue) (A1–A26). They are implemented as:

| Group | Tool | Examples |
|---|---|---|
| BFF and session units | Vitest (node) | CSRF (A22), traversal/SSRF (A24), cookie tampering (A19), dev adapters in production (A26) |
| Browser-level | Playwright | Hidden resources render the generic 404 with no data in HTML/RSC (A2, A8, A21); logout/user-switch cache purge (A5); open redirect corpus (A23); XSS payload corpus across templates with CSP violation listener (A25) |
| Headers and caching | Playwright request fixtures | Security headers and CSP profile per route class (08 §7); `private, no-store` on app/admin/`/api` (A6); ISR pages identical signed-in vs anonymous (A7) |
| Privacy | Playwright + log capture | Using Nearby leaves no coordinates in URL, storage, analytics stub or server logs (A15) |
| Authorization UI | Component tests | Behaviour codes per 03 §3 for each ✗/C row the UI renders |
| Dependency and secrets | CI | `npm audit --audit-level=high`, gitleaks, `NEXT_PUBLIC_` secret-name check, bundle scan for secret patterns |

Backend-owned **B** rows run in the backend security suite (doc 10 §3.4). The nightly live E2E run re-executes A1, A4, A8, A10, A13, A14, A16 and A20 against the backend dev stack to confirm the web and backend agree.

## 9. E2E journeys (brief §30)

Environment legend: **M** = runs on the mock in PR CI; **L** = runs nightly against the local backend dev stack (docker compose, dev IdP, dev billing, stub AI; doc 10 §4); **S** = runs pre-release on staging (real sandboxes: IdP test tenant, Stripe test mode, AI provider with low quota).

| # | Journey | Steps | Key assertions | Env | Req |
|---|---|---|---|---|---|
| J1 | **Registration → personalized feed** | Open `/` → "Join the Community" → `/register` → dev IdP persona "new traveler" (birth date ≥ 18, consents) → onboarding: name, language, interests, home country (skip), upcoming destination "Rio de Janeiro", location (Not now), discovery (left off) → lands on `/feed` | Session cookie is HttpOnly; `/onboarding` not reachable again; feed non-empty; context label shows "Rio de Janeiro · selected destination"; discovery is off in settings; under-18 birth date → `age_restricted` message and no session | M, L, S | PROF-001/002, FEED-001, DISC-001, AUTH-008 |
| J2 | **Publishing a travel post** | Signed-in verified user → composer → photo upload → tag destination (precision "destination") → visibility public → publish | Upload progress; post appears at the top of the feed and on `/stories/{id}` (public); no EXIF in the served image (L/S); unverified user → verify-email prompt; private post → `/stories/{id}` 404 | M (media mocked), L, S | POST-001/002/004/008, AUTH-004 |
| J3 | **Traveler discovery → connection** | User A enables discovery (consent + safety guidance) for Lisbon → `/companions` shows B (also opted in) with area label and date overlap → A sends request → B accepts in `/companions/requests` | No distance or coordinates in DOM or network responses; B appears only after both opt in; decline → A sees `declined` and the cooldown blocks re-request; invisible mode → `discovery_invisible` state | M (partial), L, S | DISC-001..006, CONN-001..006 |
| J4 | **Connection → private chat** | A and B connected → A opens DM → sends text and photo → B (second browser context) receives in realtime → B goes offline, A sends 3 messages → B reconnects | Delivery ack; ordering by `seq`; catch-up fills the gap; no duplicates on retry; typing indicator; read receipts honour settings; non-connected user C gets `connection_required`; C visiting the conversation URL gets 404 | L, S (mock: 503 state asserted) | DM-001..008, T-AZ-01 |
| J5 | **Premium subscription → group creation** | Free user opens `/groups/new` → upsell → `/pricing` → checkout (L: dev billing grant via backend dev endpoint; S: Stripe Checkout test card) → `/membership/success` polls → entitlement appears → create group | Before purchase `POST /v1/groups` (forced via API) → `403 entitlement_required`; success page grants nothing until the webhook/dev event; group created with the user as owner; `groups.owned` quota shown | L, S (mock: buy disabled asserted) | GRP-001, BILL-003, ADR-0012 |
| J6 | **Group invite → group chat** | Owner invites B directly and creates an invite link → B (free) accepts → B posts in group chat; moderator removes C | Free user can join (GRP-008); capacity limit enforced; removed member's open chat closes and history fetch → 404; B cannot DM C without a connection | L, S | GRP-005/008/012, GCHAT-001/005/007 |
| J7 | **Challenge creation → result** | Premium owner creates a riddle challenge (badge prize, first-correct) → scheduler activates → member submits wrong then right answer → results published | Answers absent from all member payloads; attempts decrement; cooldown respected; winner deterministic; result shows award and timestamp; cash prize rejected at creation | L, S | CHAL-001..011, CHAL-013 |
| J8 | **AI itinerary creation and saving** | User opens the assistant → picks Rio, 5 days, beaches/food/photography/adventure → generates → previews days on map → regenerates one day → saves to a new trip → reorders items (keyboard alternative) → reloads | Structured days with places and durations; `unverified` items labelled; no unsourced prices/hours; quota decrements; saved trip persists and reflects order after reload; `If-Match` conflict path shows the merge prompt | L (stub AI), S | AI-002..004, AI-009, TRIP-001/002 |

Supporting journeys (smoke, every PR on the mock): public homepage → destination page → story; locale switch keeps the path; signed-in `/` → `/feed`; logout.

## 10. Responsive and browser matrix

| Viewport | Width × height | Projects |
|---|---|---|
| Mobile S | 360 × 740 | Chromium (Android emulation), WebKit (iPhone emulation) |
| Mobile L | 414 × 896 | WebKit |
| Tablet | 768 × 1024 (portrait) and 1024 × 768 | Chromium, WebKit |
| Desktop | 1280 × 800, 1440 × 900 | Chromium, Firefox, WebKit |
| Wide | 1920 × 1080 | Chromium (layout checks only) |

| Browser | Support level | Where tested |
|---|---|---|
| Chrome / Edge (last 2) | Full | Playwright Chromium (PR + nightly) |
| Firefox (last 2, ESR) | Full | Playwright Firefox (nightly) |
| Safari macOS + iOS (last 2) | Full | Playwright WebKit (nightly) + manual real-device pass per release |
| Samsung Internet (last 2) | Full | Manual pass per release |
| Others / older | Graceful degradation (content readable, no JS-only dead ends on public pages) | — |

Feature checks with fallbacks are tested explicitly: Geolocation denied, Web Share unavailable, notifications unsupported, service worker unavailable, WebSocket blocked (realtime → REST polling fallback banner).

## 11. Visual regression (from Phase 3)

Playwright screenshots of home, city page, story, feed, composer, messages, group chat, admin queue in light/dark × mobile/tablet/desktop. Threshold 0.1 % pixel diff with anti-aliasing tolerance. Run nightly; diffs reviewed in the PR that changes UI. A hosted service is evaluated in Phase 9.

## 12. Test data and the mock

| Data | Source | Rules |
|---|---|---|
| Destinations and places | `packages/api-client/src/mock/fixtures` | General, verifiable descriptions; no live facts; no third-party photos (01 §7.1) |
| Personas | Mock fixtures + backend dev seed (same IDs where possible) | free verified, free unverified, premium, under-age attempt, moderator, admin, superadmin; two travelers opted into discovery in the same city |
| Posts | Fixtures with every visibility value and moderation state | Exercises 404 paths and leakage checks |
| Adversarial content | XSS/Unicode corpus fixtures (RTL override, zero-width, emoji, long strings) | Used by A25 and layout tests |
| Time | Fixed clock in unit tests; Playwright `clock` API for relative times and hint unlocks | Avoids flaky time assertions |
| Isolation | Mock state reset per test worker via a test-only reset hook (dev/test only) | No cross-test coupling |

**No production data** in any test environment (doc 10 §4).

## 13. CI gates (`.github/workflows/ci-web.yml`) and flake policy

| Gate | Threshold | Stage |
|---|---|---|
| ESLint + Prettier check | 0 errors | PR |
| `tsc --noEmit` (all workspaces) | 0 errors | PR |
| Unit + component + integration (Vitest) | 100 % pass | PR |
| Coverage | ≥ 90 % lines for `packages/api-client`, `packages/validation`, and `apps/web/src/server/**` (session, CSRF, env, BFF); ≥ 70 % overall web | PR |
| i18n key parity | 0 missing keys | PR |
| Contract checks | Pass (required once the spec exists) | PR |
| `next build` | Success; route bundle budgets respected | PR |
| E2E smoke + J1, J2, J3 (mock) on Chromium, with axe | 100 % pass, 0 axe violations | PR |
| SEO check (07 §10) | Pass | PR |
| Security tests (08 §12 W rows runnable on the mock) | 100 % pass | PR |
| `npm audit --audit-level=high`, gitleaks, secret-prefix check | 0 unwaived | PR |
| Lighthouse CI (subset) | Budgets met | PR |
| Full E2E matrix (all projects, J1–J8 on the live dev stack), visual regression, full Lighthouse | Pass | Nightly |
| Staging E2E (J1–J8) + manual a11y and real-device pass | Pass | Pre-release |

**Flake policy:** Playwright `retries: 2` in CI only, with trace, video and screenshot on first retry. A test that passes only on retry is reported as **flaky** in the run summary. Flaky tests are quarantined with an `@quarantine` tag and a linked issue within 1 working day, kept in quarantine for at most 7 days, and then fixed or deleted with sign-off. Quarantined tests still run nightly but do not gate. Flake rate target < 1 % of E2E runs. No arbitrary `waitForTimeout`: use web-first assertions and network/route events.

## 14. Traceability

Web tests carry PRD IDs: Vitest/Playwright test titles include `[REQ:FEED-001]`, or a `/* req: FEED-001 */` comment (doc 10 §2 convention for TypeScript). The traceability script (`scripts/trace_requirements.py`, backend stream) is extended to scan `apps/web` and `packages/*` (request to the backend stream). Security tests carry threat IDs (`T-WEB-03`, `T-AZ-01`).

## 15. Open questions

1. The local backend dev stack must expose a dev-only way to grant premium (dev billing event) and to activate challenges immediately, for J5 and J7 on **L**. Request to the backend stream (doc 07 §6 `DevBillingProvider`).
2. Extending `trace_requirements.py` to TypeScript test titles: owned by the backend stream (BL-0.18).
3. Whether staging Stripe test mode and the IdP test tenant can be used from CI (secrets in CI for pre-release jobs) needs DevOps approval (11).
