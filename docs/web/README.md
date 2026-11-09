# Travel Buddy Web: documentation index

The web platform is the public SEO site, the traveler web app and the admin area, built as one Next.js application in `apps/web` with shared `packages/*`. It is a client of the shared FastAPI platform ([doc 02](../02-system-architecture.md)) and the normative contract ([`contracts/openapi/openapi.yaml`](../../contracts/openapi/openapi.yaml)).

## The 14 required initial outputs (master brief §32)

| # | Output | Document |
|---|---|---|
| 1 | Full web application architecture | [01: Architecture](01-architecture.md) |
| 2 | Route map | [01 §10](01-architecture.md#10-route-map-canonical) (canonical) · [02: Routes & sitemap](02-routes-and-sitemap.md) (expanded) |
| 3 | Sitemap | [02 §XML sitemap and sitemap tree](02-routes-and-sitemap.md) |
| 4 | User role & permission matrix | [03: Roles & permissions](03-roles-permissions.md) |
| 5 | Design system | [04: Design system](04-design-system.md) · code: `packages/ui/src/tokens.css` |
| 6 | Reusable component inventory | [04 §Component inventory](04-design-system.md) |
| 7 | Page & screen inventory (purpose, interactions, components, API, states, authz, acceptance criteria) | [05: Page inventory](05-page-inventory.md) |
| 8 | API integration contracts | [06: API integration](06-api-integration.md) (web-consumed subset; `openapi.yaml` is normative) |
| 9 | State management plan | [01 §9](01-architecture.md#9-state-management-plan) |
| 10 | SEO strategy | [07: SEO strategy](07-seo-strategy.md) |
| 11 | Security & privacy plan | [08: Security & privacy](08-security-privacy.md) (extends [doc 08](../08-privacy-security-threat-model.md)) |
| 12 | Development backlog + versioned roadmap (§34) | [09: Backlog](09-backlog.md) (links to [doc 09](../09-development-backlog.md)) |
| 13 | Test strategy | [10: Test strategy](10-test-strategy.md) (extends [doc 10](../10-test-strategy.md)) |
| 14 | Deployment plan | [11: Deployment](11-deployment.md) (web requirements on [doc 11](../11-infrastructure-deployment.md) / `infra/`) |

Decisions: [ADR-0009](../adr/0009-web-monorepo-layout.md) monorepo · [ADR-0010](../adr/0010-nextjs-for-web-and-admin.md) one Next.js app incl. admin · [ADR-0011](../adr/0011-web-bff-cookie-sessions.md) BFF + sealed HTTP-only cookies · [ADR-0012](../adr/0012-web-billing-provider.md) Stripe (proposed) · [ADR-0013](../adr/0013-realtime-tickets-for-browsers.md) realtime tickets · [ADR-0014](../adr/0014-web-maps-maplibre.md) MapLibre GL JS.

## Implementation status (2026-11-09)

The platform backend's login is not live yet (backlog BL-1.01), so the web currently runs against the **server-side mock adapter**. It is a contract simulator for `/v1`: it emits the generated OpenAPI shapes, follows the auth rules and returns 404 instead of 403 where doc 02 requires. It is labelled "Mock data" in the UI and is refused outside development/test. Switching to the real platform only requires `TB_API_MODE=live` and `API_BASE_URL`.

| Phase | Area | Status | Verified by |
|---|---|---|---|
| 1 | Monorepo, Next.js 16 / React 19 / TS 5.9 strict, Tailwind 4 tokens (light + dark), UI primitives | **Done** | `npm run check` |
| 1 | i18n: en, es, pt-BR, fr, de (543 strings, ICU plurals, RTL-ready layout) | **Done**. Non-English copy is machine-assisted and needs native review | i18n parity unit tests |
| 1 | Contract types generated from `openapi.yaml` (`npm run gen:types`, CI drift check) | **Done** | CI `gen:types:check` |
| 1 | BFF sessions: sealed cookie, refresh, CSRF double-submit, logout; dev identity provider | **Done** | unit + E2E |
| 1 | OIDC identity adapter (Google / Apple / email via the IdP) | **Not started**. The port exists and fails loudly | — |
| 1 | Security headers; nonce CSP on dynamic routes; `'unsafe-inline'` scripts only on static public pages | **Done** | E2E header checks |
| 2 | Homepage (all 12 sections), destinations directory, country and city pages, public stories, pricing, download, about, legal drafts | **Done** (ISR / SSG) | E2E, axe (no serious violations) |
| 2 | SEO: metadata, canonical, hreflang (+ x-default), JSON-LD (Organization, WebSite, TouristDestination, BreadcrumbList, FAQPage, SocialMediaPosting, ItemList), sitemap, robots | **Done** | E2E |
| 3 | Registration (18+ gate), seven-step onboarding (discovery off by default), location-aware feed (4 tabs, transparent context, rounded request-scoped location), composer (text posts with drafts), reactions, bookmarks, comments, report and block, profile, privacy settings | **Done** (photo/video uploads wait for the media service) | E2E journeys |
| 4–8 | Companions, messaging, groups, challenges, AI assistant, trips, explore map, audio guides, membership checkout, admin tools | **Not started**. Honest "arriving in phase N" pages; the mock returns `503 feature_not_available_in_mock` | — |
| 2–3 | Platform cache-revalidation webhook, search-indexing consent, permission-gated admin nav, staff idle timeout, account restrictions | **Done** | unit + live webhook checks + E2E |
| 9 | CI (`.github/workflows/ci-web.yml`), container image (`apps/web/Dockerfile`) | **Written.** The image has not been built locally (no Docker on the dev machine); the CI job builds it | — |

## Run it

```bash
npm install
npm run dev                         # http://localhost:3000 (mock adapter + dev identity)
npm run check                       # lint + typecheck (all workspaces) + unit tests
APP_ENV=test npm run build          # production build
cd apps/web && APP_ENV=test npx playwright test   # E2E (starts `next start` on :3100)
```

Sign in through **Log in → any provider → persona picker**: Amelia (UK traveler in Rio), Lucas (premium), Priya (moderator, admin area), and others. Or register a new traveler.

## Open questions (consolidated from the doc forks; owners in brackets)

1. ~~Cache invalidation for public stories~~ **Resolved**: the platform's outbox calls the signed `POST /api/revalidate` webhook (contract `webhooks: webCacheRevalidation`, SAFE-012). The web side is implemented and verified: HMAC signature, 300 s replay window, two rotation secrets, idempotency, and `expire: 0` for privacy reasons. The 60 s story revalidate stays as a backstop.
2. **Multi-replica ISR** [infra]: with two or more web replicas, ISR needs a shared cache handler (Redis) or the revalidation webhook above.
3. **`NEXT_PUBLIC_*` values are inlined at build**, so images are built per environment until runtime config injection lands (09, Phase 9).
4. **Authenticated profile route** [product]: `/u/[handle]` stays public and cookie-free. An authenticated `/people/[handle]` is recommended for relationship controls (02 Q2).
5. **Default post visibility** [product]: currently `followers`, and Public is never preselected. Product should confirm.
6. ~~Backend requests~~ **All answered (contract updated 2026-11-09)**:
   * search-indexing consent (PROF-008): implemented. Stories are `noindex` and left out of the sitemap unless the post has `indexable: true`; a settings toggle controls it.
   * `PlatformPermission` + `Me.permissions`: implemented. Admin navigation is permission-gated.
   * MFA, idle and absolute session limits (ADM-007/008): a 30-minute idle guard and re-auth/MFA prompts are implemented.
   * `X-Audit-Justification` (ADM-009): supported by the client and validated by the BFF, ready for the Phase 8 admin screens.
   * `MyAccount.restrictions` (SAFE-013): implemented. The composer explains posting limits.
   * Web Push goes through the device registry (NOTIF-005), and feature flags come from `GET /v1/client-config`. Both are documented, and the UI arrives with Phase 4.
7. **Legal texts** [legal]: `/legal/*` pages are labelled drafts and `noindex` until reviewed.
8. **Real photography** [content]: destination covers will show licensed images with the required `MediaRef.attribution`. Until then, deterministic branded artwork is used and no unlicensed photos appear.
