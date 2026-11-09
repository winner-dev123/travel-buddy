# Web 09 — Web Development Backlog and Versioned Roadmap

| | |
|---|---|
| **Status** | Draft v1.0 — Web Phase 1 |
| **Owner** | Web engineering lead · Product |
| **Builds on** | [Web 01](01-architecture.md) (route map §10, phases) · [09 — Development backlog](../09-development-backlog.md) (backend/mobile items `BL-x.yy`; normative for backend work) · [PRD](../01-prd.md) (requirement IDs) |
| **Sizing** | Same as doc 09: S ≤ 2 d, M ≤ 5 d, L ≤ 10 d, XL > 10 d (one engineer). Re-estimated at each phase kickoff |
| **Item IDs** | `WEB-P<phase>-<nnn>`. Web phases follow the product brief §31 (1–9). They are **not** the same numbering as the backend phases in doc 09 (0–7); see §1 |

Status values: **Done** · **In progress — web scaffold** (being built against the mock adapter, 01 §7.1) · **Planned** · **Blocked** (dependency named).

A web item is only **Done** when it works against the live platform API (not just the mock), meets its acceptance criteria as automated tests (10), and passes the web DoD (§13).

---

## 1. Phase mapping (web ↔ backend)

| Web phase (brief §31) | Theme | Depends on backend phase (doc 09) | Key backend items |
|---|---|---|---|
| P1 Foundation | Repo, Next.js, design system, API client, auth (BFF), layouts, i18n | Phase 0, Phase 1 (identity) | BL-0.05, BL-1.01, BL-1.02, BL-1.03 |
| P2 Public website | Home, destinations, public stories, SEO | Phase 1 | BL-1.05, BL-1.06, BL-1.10, BL-1.23 |
| P3 Social experience | Onboarding, feed, composer, interactions, profiles | Phase 1 | BL-1.04, BL-1.07, BL-1.08, BL-1.10–1.14, BL-1.16 |
| P4 Companions and messaging | Discovery, connections, DMs, notifications | Phase 2, Phase 3 (messaging) | BL-2.01–2.07, BL-3.03–3.06, BL-3.15 |
| P5 Groups and monetization | Pricing, checkout, groups, invitations, group chat | Phase 3 | BL-3.01, BL-3.02, BL-3.07–3.10, BL-3.14 |
| P6 AI and travel planning | Assistant, itineraries, trips, maps, audio guides | Phase 4 | BL-4.01–4.08 |
| P7 Gamification | Riddles, teams, prizes, results | Phase 5 | BL-5.01–5.07 |
| P8 Administration | Analytics, moderation, destinations, billing ops, challenge admin | Phase 1 (min), Phase 6 | BL-1.14, BL-1.22 (delivered by web per ADR-0010), BL-6.02 |
| P9 Production readiness | Security, a11y, SEO validation, performance, deployment, monitoring | Phase 6 | BL-6.03–6.07 |

Because the backend is built in parallel, every web phase can start against the mock adapter. A phase can only exit when its backend dependencies are live in staging.

## 2. Phase 1 — Foundation

| ID | Story | Acceptance criteria (summary) | Depends | Size | Status |
|---|---|---|---|---|---|
| WEB-P1-001 | Monorepo with npm workspaces (`apps/web`, `packages/*`), Node 24, shared tsconfig | `npm ci` + `npm run typecheck` green; mobile stays a standalone project (ADR-0009) | ADR-0009 | S | In progress — web scaffold |
| WEB-P1-002 | Next.js 16 App Router app, TypeScript strict, ESLint flat config, Prettier | `strict: true`, `noUncheckedIndexedAccess`; lint 0 errors; `next build` passes | — | S | In progress — web scaffold |
| WEB-P1-003 | Design tokens (CSS + TS), light/dark themes, typography, focus states, motion | Tokens in `packages/ui`; AA contrast verified (01 §13); `prefers-color-scheme` + manual toggle; reduced motion respected | 04 | M | In progress — web scaffold |
| WEB-P1-004 | Accessible UI primitives (Button, Input, Select, Dialog, Tabs, Menu, Avatar, Badge, Skeleton, Toast, EmptyState, ErrorState) | Radix-based; keyboard and screen-reader tested; unit tests per component | 04 | M | In progress — web scaffold |
| WEB-P1-005 | i18n with next-intl: en, es, pt-BR (`/pt-br`), fr, de; locale switcher; RTL-ready layout | Key-parity test (I18N-001); locale-aware formatters (I18N-002); `<html lang dir>` | 02 §4 | M | In progress — web scaffold |
| WEB-P1-006 | `@travelbuddy/domain-types` hand-written from 06; generation script stub | Types compile; `contracts:generate` wired but no-op until the spec exists | 06, BL-0.05 | S | In progress — web scaffold |
| WEB-P1-007 | `@travelbuddy/validation` Zod schemas (forms + response guards) | Shared limits match 06; unit tests | 06 | S | In progress — web scaffold |
| WEB-P1-008 | `@travelbuddy/api-client`: transports (fetch, BFF, mock), `ApiError`, retries, idempotency keys, cursor pages | Unit tests for error mapping, retry rules (never on `quota_exceeded`), idempotency reuse | 06 §6 | M | In progress — web scaffold |
| WEB-P1-009 | Mock adapter (`@travelbuddy/api-client/mock`) with boot guard and `X-TB-Mock` banner | Refuses to start outside dev/test; 503 `feature_not_available_in_mock` for payments/AI/chat (01 §7.1) | — | M | In progress — web scaffold |
| WEB-P1-010 | Environment validation (`src/server/env.ts`) | Invalid or unsafe combinations fail at boot (mock or dev IdP in staging/prod; short `SESSION_SECRET`) | 11 | S | In progress — web scaffold |
| WEB-P1-011 | Session sealing (JWE) + `tb_session`/`tb_csrf`/`tb_oidc` cookies | Unit tests for seal/unseal, tamper rejection, key rotation (`kid`) | ADR-0011 | M | In progress — web scaffold |
| WEB-P1-012 | `proxy.ts`: locale routing, session presence gating, proactive refresh, security headers, nonce CSP for dynamic routes | Redirect matrix from 02 §3 covered by tests; headers per 08 §7 | 02 §3, 08 §7 | M | In progress — web scaffold |
| WEB-P1-013 | BFF proxy `/api/v1/[...path]` | CSRF, path/method allow-lists, refresh on `token_expired`, header stripping, `/v1/dev/**` blocked, admin gate (08 A16, A22, A24) | ADR-0011 | M | In progress — web scaffold |
| WEB-P1-014 | `IdentityProvider` port + `DevIdentityProvider` (`/dev/login` personas) using `POST /v1/dev/idp/token` → `/v1/auth/login` | Dev login reaches `/feed` or `/onboarding`; 404 outside dev/test | BL-1.01 | M | In progress — web scaffold |
| WEB-P1-015 | `OidcIdentityProvider` (Authorization Code + PKCE, confidential client) | Login/register/logout against the IdP test tenant in staging | **Blocked**: IdP vendor (PRD Q-1), BL-1.01 | M | Blocked |
| WEB-P1-016 | `/login`, `/register` (birth date, terms + privacy versions), `/forgot-password`, `/verify-email`, `/auth/error` | AUTH-001..005, AUTH-008, AUTH-009 hand-offs; `age_restricted` handled; uniform errors | BL-1.03 | M | In progress — web scaffold |
| WEB-P1-017 | Layouts: marketing header/footer, auth layout, traveler shell (sidebar desktop, bottom nav mobile), admin shell | Responsive at 360/768/1024/1440; skip links; landmarks | 02 §5 | M | In progress — web scaffold |
| WEB-P1-018 | Query client provider, query-key factory, Zustand store conventions | 01 §9 rules encoded; devtools only in dev | — | S | In progress — web scaffold |
| WEB-P1-019 | `ci-web.yml`: install, lint, typecheck, unit, build, e2e (mock) | Required checks on PRs touching `apps/web`, `packages/*` | 10, 11 | S | In progress — web scaffold |
| WEB-P1-020 | `apps/web/Dockerfile` (standalone, non-root) | Image builds in CI; container starts with health check | 11 | S | In progress — web scaffold |
| WEB-P1-021 | Logging and request IDs (redaction list) | Unit test proves `near`, `lat`, `lng`, `token`, `ticket`, cookies are redacted | 01 §16 | S | Planned |

## 3. Phase 2 — Public website

| ID | Story | Acceptance criteria (summary) | Depends | Size | Status |
|---|---|---|---|---|---|
| WEB-P2-001 | Homepage with the 12 sections of brief §6 (hero, search, discovery intro, popular destinations, featured stories, AI demo (labelled example), companions, groups, audio guides, premium, app links, footer) | SSR/ISR; LCP ≤ 2.0 s budget; signed-in → `/feed`; all copy localized | WEB-P1-* | L | In progress — web scaffold |
| WEB-P2-002 | Destination search with autocomplete (`/v1/destinations/search`) | Accent/typo tolerant (DEST-001); keyboard accessible combobox | BL-1.06 | M | In progress — web scaffold |
| WEB-P2-003 | `/destinations` directory with region/country/category filters (URL state) | Filtered views `noindex` (02); empty and error states | BL-1.05 | M | In progress — web scaffold |
| WEB-P2-004 | `/destinations/[country]` and `/destinations/[country]/[city]` pages | Overview, hero (licensed or branded placeholder), map (lazy), attractions, stories, suggested itineraries (editorial), audio guides (when available), FAQs, CTA; localized names (DEST-002); fallback copy marked `lang="en"` | BL-1.05, `destinations/lookup` (06 §10) | L | In progress — web scaffold |
| WEB-P2-005 | Location map component (MapLibre, lazy, dev demo style label) | Not in first-load JS; keyboard-operable; text alternative | ADR-0014 | M | In progress — web scaffold |
| WEB-P2-006 | `/stories` and `/stories/[storyId]` (public + approved only, `PublicPost`) | Hidden → 404; attribution, tags, media, date, related, Report (gate→login) | BL-1.10 | M | In progress — web scaffold |
| WEB-P2-007 | SEO infrastructure: `buildMetadata`, canonical, hreflang, sitemaps (index + chunks), robots, JSON-LD builders, OG image route | 07 §4–5 and 02 §6; CI `seo-check` green | 07 | L | In progress — web scaffold |
| WEB-P2-008 | `/pricing` (plans from `/v1/billing/products?platform=web`; buy disabled until P5) | No price hard-coded; store-subscriber state as a client island | BL-3.01 (read only) | S | In progress — web scaffold |
| WEB-P2-009 | `/download`, `/about`, legal pages (terms, privacy, cookies, community guidelines) | Content from legal; versioned; SSG | Legal copy | S | In progress — web scaffold |
| WEB-P2-010 | Cookie consent banner + `tb_consent` | No non-essential storage before consent (08 §13) | 08 | S | Planned |
| WEB-P2-011 | Destination indexing threshold applied (07 §6.2) | Below-threshold pages `noindex` and out of sitemaps | `Destination.seo` (07 §11) | S | Blocked: backend field |

## 4. Phase 3 — Social experience

| ID | Story | Acceptance criteria (summary) | Depends | Size | Status |
|---|---|---|---|---|---|
| WEB-P3-001 | Onboarding (7 steps: profile basics, language, interests/travel styles, home country (optional), current/upcoming destination, location permission explainer, discovery preference (off by default)) | Skippable non-essential steps; resumes from draft; ends on `/feed` (PROF-001, PROF-002) | BL-1.04, onboarding-complete (06 §10) | L | In progress — web scaffold |
| WEB-P3-002 | Feed `/feed` with tabs For You / Nearby / Following / Destinations | Cursor infinite scroll + "Load more" fallback; `page.reset` handling; context source label; skeletons, empty and error states (FEED-001..004) | BL-1.13 | L | In progress — web scaffold |
| WEB-P3-003 | Location controls: browse destination selector, Nearby via Geolocation (explicit gesture, rounded, never stored), radius, country/city/neighborhood filters | `PUT /v1/users/me/browse-destination`; coordinates never in URL/logs/storage (08 §9, LOC-002/003/007) | BL-1.07 | M | In progress — web scaffold |
| WEB-P3-004 | Post card (avatar, name, destination, time, media, caption, reactions, comments, bookmark, share, report) | Optimistic reaction (`POST /reactions`, `DELETE /reactions/me`) and bookmark with rollback; share only for public posts | BL-1.11 | M | In progress — web scaffold |
| WEB-P3-005 | Report dialog (reasons from backend taxonomy) and block action | Never paywalled; idempotent submit (SAFE-001/002) | BL-1.12, BL-1.14 | S | In progress — web scaffold |
| WEB-P3-006 | Post composer: text, photos, short video, destination/place tag, location precision, categories/tags, visibility, drafts, drag-and-drop, upload progress | EXIF stripped client-side where possible; media `ready` before publish; email-unverified handling (POST-001..004, AUTH-004) | BL-1.08, BL-1.10 | L | Planned |
| WEB-P3-007 | Post detail with comments (one reply level), edit and delete | `edited` marker; tombstone handling (POST-005, POST-007) | BL-1.11 | M | Planned |
| WEB-P3-008 | Profile: own profile, edit, my posts, saved, privacy settings | `PublicProfile` vs `MyProfile` separation; handle change rule (PROF-003..007) | BL-1.04 | L | Planned |
| WEB-P3-009 | Public profile `/u/[handle]` (follow/request, block, report) | 404 when hidden or blocked; `noindex` until consent field exists | BL-1.04, 03 §10 Q1 | M | Planned |
| WEB-P3-010 | Notification centre (in-app list) | NOTIF-001; localized summaries from keys | BL-1.16 | M | Planned |
| WEB-P3-011 | Email-verification banner and gating | `email_unverified` → verify-email prompt with resend | BL-1.03 | S | Planned |
| WEB-P3-012 | Feed negative feedback (hide, not interested, see less) | FEED-007 | BL-1.13 | S | Planned |
| WEB-P3-013 | Feed virtualization for long sessions | INP ≤ 200 ms at 300 posts | — | M | Planned |

## 5. Phase 4 — Companions and messaging

| ID | Story | Acceptance criteria (summary) | Depends | Size | Status |
|---|---|---|---|---|---|
| WEB-P4-001 | Discovery consent flow with safety guidance; discovery session start/stop; invisible mode; persistent indicator | DISC-001, DISC-002, DISC-006, DISC-010, SAFE-008 | BL-2.01, BL-2.02 | M | Planned |
| WEB-P4-002 | `/companions` directory: destination selector, traveler cards (photo, name, bio, interests, area, date overlap, connection status), filters | No distances or coordinates (DISC-004); rate-limit states (DISC-009) | BL-2.03 | L | Planned |
| WEB-P4-003 | Connection actions and `/companions/requests` inbox | Request/accept/decline/cancel/remove; cooldown and restriction errors (CONN-001..008) | BL-2.04, BL-2.05 | M | Planned |
| WEB-P4-004 | Realtime client: ticket auth, reconnect with jittered backoff, seq gap catch-up, dedupe | Unit tests with a fake socket; `session.revoked` handling | BL-3.04, BL-3.15 | L | Planned |
| WEB-P4-005 | `/messages` list + conversation view (desktop two-pane, mobile stacked) | Unread counts, search, history pagination, composer, photos, replies, reactions, typing, receipts (reciprocal), mute, block, report, failed-send retry (DM-001..012) | BL-3.03–3.05 | XL | Planned |
| WEB-P4-006 | Web Push opt-in (settings toggle, never on first visit) | VAPID subscription; payloads per NOTIF-004 | `POST /v1/users/me/devices` webpush variant (NOTIF-005) | M | Ready (contract accepted) |
| WEB-P4-007 | Notifications realtime badge + toasts | `notification.new` frames | BL-3.06 | S | Planned |
| WEB-P4-008 | Connections list on profile | Remove connection silently | BL-2.04 | S | Planned |

## 6. Phase 5 — Groups and monetization

| ID | Story | Acceptance criteria (summary) | Depends | Size | Status |
|---|---|---|---|---|---|
| WEB-P5-001 | Membership: pricing → checkout hand-off (`POST /v1/billing/checkout-sessions`) → `/membership/success` polling entitlements | Success page grants nothing; timeout messaging; hides purchase for store subscribers (ADR-0012) | BL-3.14 | M | Planned |
| WEB-P5-002 | Membership dashboard: plan, status (grace, retry, paused), manage (Stripe portal or store link), purchase history | doc 07 §4 states rendered | BL-3.02, BL-3.14 | M | Planned |
| WEB-P5-003 | Upsell sheet and quota meters driven by `Entitlements` | `entitlement_required` and `quota_exceeded` handled distinctly | BL-3.02 | S | Planned |
| WEB-P5-004 | `/groups` (My Groups, Invitations; Discover behind flag) | Private invite-only v1 (GRP-004) | BL-3.07 | M | Planned |
| WEB-P5-005 | `/groups/new` creation form (name, description, cover, destination/trip, dates, interests, capacity) | Server-verified `groups.create` + `groups.owned` (GRP-001, GRP-013) | BL-3.07 | M | Planned |
| WEB-P5-006 | Group detail: overview, members, shared itinerary, settings; admin capabilities from `viewer_permissions` | Lapse/grace states shown to owner/admins only (doc 07 §5) | BL-3.07, BL-3.10 | L | Planned |
| WEB-P5-007 | Invitations: direct and links (create, revoke, redeem via an `/invite/[token]` route, which is **not yet in 01 §10** and must be added there; token never logged, `noindex`) | Capacity and invalid-invitation states (GRP-005, GRP-012) | BL-3.08 | M | Planned |
| WEB-P5-008 | Group chat: shared room, avatars, replies, reactions, mentions, pins, announcements, media, moderation (remove, restrict), notifications | GCHAT-001..007; removed member loses access immediately | BL-3.09 | L | Planned |
| WEB-P5-009 | "Request private chat" from group members → connection request | Group membership grants no DM (GCHAT-005) | BL-2.04 | S | Planned |
| WEB-P5-010 | Ownership transfer and archive flows | GRP-010, GRP-011 | BL-3.10 | S | Planned |

## 7. Phase 6 — AI and travel planning

| ID | Story | Acceptance criteria (summary) | Depends | Size | Status |
|---|---|---|---|---|---|
| WEB-P6-001 | AI assistant (global drawer + `/assistant`): preferences, suggested prompts, structured itinerary preview, regenerate/modify, save to trip, share | `unverified` items labelled; costs only with source and freshness; quota meter (AI-002..004, AI-009) | BL-4.02, BL-4.03 | L | Planned |
| WEB-P6-002 | Conversational chat (SSE streaming through the BFF) | Behind a flag until a quota key exists (03 §10 Q3) | AI-006, BL-4.02 | M | Blocked: quota policy |
| WEB-P6-003 | `/trips`, `/trips/new`, trip detail with daily itinerary | Create with destination, dates, preferences, budget, travelers (TRIP-001) | BL-4.04 | L | Planned |
| WEB-P6-004 | Itinerary editor: drag-and-drop on desktop + accessible move up/down/menu alternative, add/remove places, change dates, save with `If-Match` and merge prompt on `412` | WCAG 2.2 drag alternative (2.5.7); sync with mobile via the same API | BL-4.04 | L | Planned |
| WEB-P6-005 | Route preview on the trip map | `GET /v1/routes/preview`; provider attribution | BL-4.06 | M | Planned |
| WEB-P6-006 | `/explore`: split view (filters + cards + map), mobile map/list toggle, clustering, viewport loading, saved places | Debounced bbox queries; map lazy; keyboard-accessible list equals map content | BL-4.01, BL-4.06 | XL | Planned |
| WEB-P6-007 | Attraction pages (public, SEO) | 07 §5 `TouristAttraction`; licensed data with freshness | BL-4.01 | M | Planned |
| WEB-P6-008 | Guides library and guide pages (free/premium, content purchases) | Premium bodies only for entitled users (GUIDE-004) | BL-4.07 | M | Planned |
| WEB-P6-009 | Audio tour player `/tours/[tourId]`: stops, map markers, progress, speed, save; manual stop playback; optional foreground location triggering where supported | No promise of background geofencing on the web (brief §21) | BL-4.07 | L | Planned |
| WEB-P6-010 | PWA: manifest, service worker for offline guide/audio packages within `offline.packages` quota; signed-manifest verification | Never caches `/api/*` or app HTML (08 T-WEB-25); clear online-only labels (OFF-003) | BL-4.08 | L | Planned |

## 8. Phase 7 — Gamification

| ID | Story | Acceptance criteria (summary) | Depends | Size | Status |
|---|---|---|---|---|---|
| WEB-P7-001 | Challenge dashboard (Active, Upcoming, Completed) in group detail | Membership-scoped; no answers in any payload (CHAL-008) | BL-5.01 | M | Planned |
| WEB-P7-002 | Challenge creation form (title, riddle, image, hints, start, deadline, attempts, validation, winner policy, prize, mode) | Prohibited reward types rejected with clear errors (CHAL-012/013); real-world rewards show the review gate (CHAL-014) | BL-5.01, BL-5.06 | L | Planned |
| WEB-P7-003 | Participation: view riddle, reveal hints, submit answer, attempts and cooldown display, team thread, captain-only submit | CHAL-004, CHAL-005 | BL-5.03, BL-5.04 | L | Planned |
| WEB-P7-004 | Results view (winner/team, award, completion timestamp, summary) and disputes | CHAL-011, CHAL-016 | BL-5.07 | M | Planned |
| WEB-P7-005 | Badges on profiles | Badge catalog rendering | BL-5.06 | S | Planned |

## 9. Phase 8 — Administration

| ID | Story | Acceptance criteria (summary) | Depends | Size | Status |
|---|---|---|---|---|---|
| WEB-P8-001 | Admin shell with permission-filtered navigation, 404 for non-staff, step-up re-auth for sensitive actions | 03 §4, 08 §11 | Permission enum (03 §10 Q2) | M | Planned |
| WEB-P8-002 | **Minimal moderation console** (report queue, review with evidence snapshot, actions with reason codes). Fulfils BL-1.22 per ADR-0010, so it is pulled forward to ship with backend Phase 1 | ADM-001..003, SAFE-003 prioritization | BL-1.14 | L | Planned (pull forward) |
| WEB-P8-003 | User administration: search, detail, justified sensitive reveal, suspend/reinstate, moderation history | ADM-003; audited | BL-1.14 | M | Planned |
| WEB-P8-004 | Appeals | Decisions recorded | BL-6.02 | S | Planned |
| WEB-P8-005 | Dashboard overview metrics from `/v1/admin/metrics/overview` | Real aggregates only; empty state when no data; no fabricated series | BL-6.02 | M | Planned |
| WEB-P8-006 | Operational dashboard (moderation SLAs, outbox lag, job failures) | ADM-006 | BL-6.02 | S | Planned |
| WEB-P8-007 | Group investigation and suspension | — | BL-3.07 | S | Planned |
| WEB-P8-008 | Challenge administration: flagged submissions, disputes, reward review and fulfilment | CHAL-014..016 | BL-5.05–5.07 | M | Planned |
| WEB-P8-009 | Destination management: create/edit, localizations, licensed image metadata, FAQs, featured placement | ADM-004, DEST-004; `If-Match` | BL-1.05 | L | Planned |
| WEB-P8-010 | Guide review | — | BL-4.07 | S | Planned |
| WEB-P8-011 | Subscription administration: status lookup, billing events and failures, config, promo grants | ADM-005, BILL-009; no card data | BL-3.01, BL-6.02 | M | Planned |
| WEB-P8-012 | Audit log viewer | Append-only, filterable | BL-0.14 | S | Planned |

## 10. Phase 9 — Production readiness

| ID | Story | Acceptance criteria (summary) | Depends | Size | Status |
|---|---|---|---|---|---|
| WEB-P9-SEC-001 | Web security suite (08 §12 W rows) in CI + nightly live run | All W cases green | — | L | Planned |
| WEB-P9-SEC-002 | CSP enforcement (report-only → enforce); hash-based CSP for static pages evaluated | 0 unexplained violations for one release | 08 §7 | M | Planned |
| WEB-P9-SEC-003 | External penetration test of the web tier + remediation | No open high/critical findings | BL-6.07 | M | Planned |
| WEB-P9-A11Y-001 | WCAG 2.2 AA audit (automated + manual screen-reader passes) | 10 §6 | — | M | Planned |
| WEB-P9-SEO-001 | SEO launch checklist (07 §12) | All items checked | — | S | Planned |
| WEB-P9-PERF-001 | Lighthouse CI budgets enforced; RUM dashboards | 01 §15 budgets at p75 | — | M | Planned |
| WEB-P9-OPS-001 | Staging/production deployment, CDN rules, alerts, runbooks | 11 checklist | infra (doc 11) | M | Planned |
| WEB-P9-GDPR-001 | Data export, deletion, consent management UIs | AUTH-010, AUTH-011, 08 §13 | BL-1.17, BL-6.03 | M | Planned |
| WEB-P9-I18N-001 | Professional translation review of es, pt-BR, fr, de | Native-speaker sign-off per locale | — | M | Planned |
| WEB-P9-REL-001 | Session management UI (`/settings/sessions`) | AUTH-006 | BL-1.02 | S | Planned |

## 11. Backend dependencies and requests

Items the web needs from the backend/contracts stream. Existing backlog items are referenced; requests without an item are marked **new**.

| Need | Backend item | Needed by | Status |
|---|---|---|---|
| OpenAPI 3.1 contract (all phases) | BL-0.05 | WEB-P1-006 | In progress (backend stream) |
| Dev IdP token endpoint `POST /v1/dev/idp/token` | BL-1.01 | WEB-P1-014 | Agreed |
| `client: "web"` sessions + 30 s refresh reuse leeway | BL-1.02 | WEB-P1-011..013 | Agreed (ADR-0011) |
| `GET /v1/destinations/lookup?path=` | **new** | WEB-P2-004 | Requested (06 §10 #1) |
| `Destination.seo.indexable` | **new** | WEB-P2-011 | Requested (07 §11 #1) |
| `POST /v1/users/me/onboarding/complete` | **new** (BL-1.04 scope) | WEB-P3-001 | Requested (06 §10 #2) |
| `MyAccount.restrictions[]` | **new** (BL-1.14 scope) | WEB-P3-011 | Requested |
| `search_indexing_enabled` privacy setting | **new** (BL-1.04 scope) | WEB-P3-009 | Requested (03 §10 #1) |
| Realtime tickets + Origin allow-list | BL-3.15 | WEB-P4-004 | Agreed (ADR-0013) |
| Web Push subscriptions | **new** (BL-3.06 scope) | WEB-P4-006 | Requested (06 §10 #4) |
| Stripe checkout/portal/webhooks | BL-3.14 | WEB-P5-001/002 | Agreed (ADR-0012 proposed) |
| AI chat quota key | **new** (doc 07) | WEB-P6-002 | Requested |
| Platform `Permission` enum | **new** (BL-0.12 scope) | WEB-P8-001 | Requested |
| Staff idle timeout + MFA for platform roles | **new** (BL-1.02 scope) | WEB-P8-001 | Requested (08 §16 #1) |
| Audit justification header | **new** (BL-1.14 scope) | WEB-P8-003 | Requested (08 §16 #2) |
| Data export/deletion/consent endpoints | BL-1.17, BL-6.03 | WEB-P9-GDPR-001 | Shapes proposed (06 §4.1) |
| Error codes `account_suspended`, `ai_unavailable` in doc 05 | **new** | WEB-P1-016, WEB-P6-001 | Requested |

## 12. Change process for new requirements (brief §34)

Every new product requirement goes through these steps, recorded in the PR that introduces it:

| Step | Action | Artifact |
|---|---|---|
| 1 | Identify the affected web pages and modules | Impact table in the PR description (routes from 01 §10 / 02, features under `src/features/*`) |
| 2 | Update the master specification | PRD requirement (backend stream owns doc 01) + web docs (01 route map, 05 page inventory) |
| 3 | Revise domain types | `packages/domain-types` (or the OpenAPI spec once generated types exist) |
| 4 | Update API contracts | Request to the backend/contracts stream; 06 updated with the web-consumed subset; mock adapter updated in the same PR |
| 5 | Update required permissions | 03 matrix rows + behaviour codes; backend policy reference |
| 6 | Assess security and privacy consequences | 08 threat rows (`T-WEB-*`) and doc 08 if the platform is affected; DPIA trigger check for location/discovery changes |
| 7 | Modify navigation or design components if necessary | 02 navigation model, 04 component inventory |
| 8 | Update automated tests | Unit/integration/E2E per 10; authorization tests per 03 §9 |
| 9 | Preserve compatibility with mobile | Additive contract changes only (06 §9); shared packages stay platform-neutral; mobile impact noted for the backend/mobile stream |
| 10 | Record significant architectural decisions | New ADR (next free number per `docs/adr/README.md`) |

Then the roadmap version (§14) is bumped if scope changes.

## 13. Web Definition of Done

Extends doc 10 §6:

1. Acceptance criteria automated (unit/integration/E2E as appropriate), with PRD IDs in test names or `/* req: … */` comments (doc 10 §2).
2. Works against the live platform API in staging, not just the mock.
3. Loading, empty, error and unauthorized states implemented and tested.
4. All strings in the five catalogs (key-parity test green).
5. Keyboard and screen-reader checks done; axe clean.
6. Performance budget for the route respected (bundle check).
7. Security checklist (08 §15) satisfied.
8. Docs updated (06 contract subset, 03 permissions, 05 page spec).

## 14. Versioned roadmap

| Version | Scope | Exit criteria | Target |
|---|---|---|---|
| **v0.1** | Web Phase 1 foundation + planning docs (01–11) | Scaffold builds, CI green, dev login → shell on the mock | Current |
| **v0.2** | Phase 2 public website on the mock, then on staging destinations | SEO checks green; public pages meet budgets | Backend Phase 1 destinations live |
| **v0.3** | Phase 3 social beta (onboarding, feed, composer, profiles) + minimal moderation console (WEB-P8-002) | E2E "registration → personalized feed" passes against staging (PROF-002, FEED-001) | Backend Phase 1 complete |
| **v0.4** | Phase 4 companions and messaging | E2E discovery → connection → DM | Backend Phases 2 + 3b |
| **v0.5** | Phase 5 groups and monetization | E2E premium (Stripe test mode) → group → invite → group chat | Backend Phase 3 |
| **v0.6** | Phase 6 AI, trips, explore, guides, PWA offline | E2E AI itinerary → saved trip | Backend Phase 4 |
| **v0.7** | Phase 7 gamification | E2E challenge creation → result | Backend Phase 5 |
| **v0.8** | Phase 8 full admin | Admin E2E for moderation, destinations, billing ops | Backend Phase 6 |
| **v1.0** | Phase 9 production launch | 11 production checklist complete; pen test closed | Commercial readiness |

Each version gets a changelog entry in `docs/web/CHANGELOG.md` (created at v0.1 release) listing added/changed items by ID.
