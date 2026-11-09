# Web 02 — Route Map and Sitemap

| | |
|---|---|
| **Status** | Draft v1.0 — Web Phase 1 |
| **Covers** | Required output #2 (route map, expanded) and #3 (sitemap) |
| **Anchor** | [Web 01 — Architecture](01-architecture.md) §5 (rendering), §6 (sessions), §10 (canonical route list), §12 (i18n) |
| **Related** | [PRD](../01-prd.md) · [03 — Roles & permissions](03-roles-permissions.md) · [04 — Design system](04-design-system.md) · [05 — Page inventory](05-page-inventory.md) · [07 — SEO strategy](07-seo-strategy.md) · [doc 08 — Threat model](../08-privacy-security-threat-model.md) |

This document expands the canonical route list in 01 §10. It does not add pages. Where it needed something 01 does not define, the item is listed under [Open questions](#9-open-questions).

---

## 1. Legend

| Column | Values |
|---|---|
| **Group** | App Router route group under `apps/web/src/app/[locale]/`: `(marketing)`, `(auth)`, `(traveler)`, `admin`. BFF handlers live outside `[locale]` in `apps/web/src/app/api/`. |
| **Render** | **SSG**: built at deploy time per locale, no revalidation. **ISR n**: static per locale, regenerated at most every *n* seconds and on demand by cache tag. **Dyn**: server-rendered per request (reads the session cookie). **Dyn+Client**: dynamic server shell, data via TanStack Query through the BFF (01 §9). |
| **Auth** | **Public**: no session needed, and the page never reads cookies. **Guest**: only meaningful without a session (signed-in users are redirected). **Session**: valid `tb_session`. **Onboarded**: Session + `onboarding_completed = true`. **Staff**: Session + platform role `support \| moderator \| admin \| superadmin` (finer permissions in 03). Group-level and entitlement checks are page-level (see 05). |
| **Robots** | Meta robots and `X-Robots-Tag`. `index,follow` is the default for indexable pages. Every non-indexable page sends both the meta tag and the header. |
| **Canonical** | **Self**: absolute URL of this page in the current locale, without query string. Other rules are spelled out. |
| **Cache-Control** | Public: CDN-cacheable (`s-maxage` = revalidate, `stale-while-revalidate`). Private: `private, no-store`. |

All routes accept the optional locale prefix described in [§4](#4-locale-prefix-rules). Paths below are written for the default locale (`en`, no prefix).

## 2. Route map

### 2.1 Public — `(marketing)` (indexable)

| Route | Page | Render | Revalidate / tags | Auth | Robots | Canonical | Cache | Phase |
|---|---|---|---|---|---|---|---|---|
| `/` | Homepage | ISR | 3600 · `home`, `destinations:featured`, `stories:featured` | Public (signed-in → `/feed`, §3) | index,follow | Self (`/` or `/{prefix}`) | Public | 2 |
| `/destinations` | Destinations directory | ISR | 3600 · `destinations:list` | Public | index,follow **without** query; `noindex,follow` when any filter or `q` is present | `/destinations` (query stripped) | Public | 2 |
| `/destinations/[country]` | Country page | ISR + `generateStaticParams` (all published countries) | 3600 · `destination:{id}` | Public | index,follow; `noindex,follow` while the destination is below the content threshold (07) | Self | Public | 2 |
| `/destinations/[country]/[city]` | Destination page | ISR + `generateStaticParams` (top 200 by popularity); long tail on demand | 3600 · `destination:{id}`, `destination:{id}:stories` | Public | as country page | Self | Public | 2 |
| `/destinations/[country]/[city]/attractions/[place]` | Attraction page | ISR on demand | 3600 · `place:{id}` | Public | index,follow (published places with content only) | Self | Public | 6 |
| `/stories` | Public stories index | ISR | 600 · `stories:list` | Public | index,follow on page 1; `noindex,follow` for `?cursor=` pages and `?destination=` filters | `/stories` | Public | 2 |
| `/stories/[storyId]` | Public travel story | ISR on demand | 600 · `post:{id}` (on-demand purge when visibility changes, see §9 Q1) | Public | index,follow **only** if `visibility = public` and moderation state is `approved` (`PublicPost` contract); otherwise HTTP 404 | Locale matching the post `language` if supported, else `en` (§2.6) | Public | 2 |
| `/u/[handle]` | Public profile | ISR on demand | 300 · `profile:{id}` | Public (signed-in enhancements are client islands) | `noindex,follow` by default; `index,follow` only when the owner opted in to search-engine indexing | Self, `en` locale only (§2.6) | Public | 3 |
| `/guides` | Guide library | ISR | 3600 · `guides:list` | Public | index,follow | Self | Public | 6 |
| `/guides/[guideId]` | Guide / audio tour description | ISR on demand | 3600 · `guide:{id}` | Public | index,follow | Self | Public | 6 |
| `/pricing` | Premium membership | ISR | 3600 · `billing:products` | Public (current-plan state is a client island) | index,follow | Self | Public | 2 (page) / 5 (checkout) |
| `/download` | App download | SSG | — | Public | index,follow | Self | Public | 2 |
| `/about` | About | SSG | — | Public | index,follow | Self | Public | 2 |
| `/legal/terms` | Terms of service | SSG | redeploy on change | Public | index,follow | Self | Public | 2 |
| `/legal/privacy` | Privacy policy | SSG | redeploy on change | Public | index,follow | Self | Public | 2 |
| `/legal/cookies` | Cookie policy | SSG | redeploy on change | Public | index,follow | Self | Public | 2 |
| `/legal/community-guidelines` | Community guidelines | SSG | redeploy on change | Public | index,follow | Self | Public | 2 |

Public pages **never** call `cookies()` or `headers()` (01 §5). Personalized fragments such as "Saved", "Your plan" or "Connect" are client components that fetch through `/api/v1/*` after hydration.

### 2.2 Authentication — `(auth)` (not indexable)

| Route | Page | Render | Auth | Robots | Canonical | Cache | Phase |
|---|---|---|---|---|---|---|---|
| `/login` | Sign in (provider choice → IdP) | Dyn | Guest | noindex,follow | Self (`next` and `error` stripped) | Private | 1 |
| `/register` | Create account (provider choice, age attestation, terms) | Dyn | Guest | noindex,follow | Self | Private | 1 |
| `/forgot-password` | Password reset hand-off to the IdP | Dyn | Guest | noindex,nofollow | Self | Private | 1 |
| `/verify-email` | Email verification status / resend | Dyn | Guest or Session | noindex,nofollow | Self | Private | 1 |
| `/onboarding` | Seven-step onboarding | Dyn+Client | Session (completed → `/feed`) | noindex,nofollow | none | Private | 3 |
| `/dev/login` | Development persona picker | Dyn | Guest; **404** unless `DevIdentityProvider` is active (`APP_ENV ∈ {development,test}`) | noindex,nofollow | none | Private | 1 |

`noindex,follow` on `/login` and `/register` lets crawlers follow links back to public pages. Reset and verification pages use `nofollow` because they can carry one-time tokens in the query string.

### 2.3 Traveler app — `(traveler)` (not indexable)

Every route in this table renders **Dyn+Client**, requires **Onboarded** unless noted, and sends `noindex,nofollow` with `Cache-Control: private, no-store`. None has a canonical tag.

| Route | Page | Auth beyond Onboarded | Phase |
|---|---|---|---|
| `/feed` | Home feed (`?tab=for-you\|nearby\|following\|destinations`) | — | 3 |
| `/posts/new` | Post composer (also opened as an intercepted modal from `/feed`) | — | 3 |
| `/posts/[postId]` | Post detail with comments | Post visible to viewer, else 404 | 3 |
| `/posts/[postId]/edit` | Edit post | Author only, else 404 | 3 |
| `/explore` | Map + list exploration (`?q=&category=&bbox=`) | — | 6 |
| `/saved` | Saved places, posts and tours | — | 3 (posts) / 6 (places, tours) |
| `/assistant` | AI travel assistant (full page; the drawer is global) | AI quota per entitlement (server) | 6 |
| `/trips` | My trips | — | 6 |
| `/trips/new` | Create trip | — | 6 |
| `/trips/[tripId]` | Trip detail + daily itinerary (`?day=YYYY-MM-DD`) | Owner or collaborator, else 404 | 6 |
| `/companions` | Traveler discovery | Viewer must have opted in to discovery to see others (05) | 4 |
| `/companions/requests` | Connection-request inbox (`?direction=incoming\|outgoing`) | — | 4 |
| `/messages` | Conversation list (desktop: list + empty pane) | — | 4 |
| `/messages/[conversationId]` | Conversation | Member, else 404 | 4 |
| `/groups` | My groups | — | 5 |
| `/groups/discover` | Discover groups. **Behind flag `groups.public_discovery`** (PRD §1.2, GRP-004); 404 when the flag is off. | — | 5 |
| `/groups/invitations` | Group invitations | — | 5 |
| `/groups/new` | Create group | Entitlement `groups.create` (server), else upsell state | 5 |
| `/groups/[groupId]` | Group overview | Member, or non-member of a discoverable group (limited view); private group non-member → 404 | 5 |
| `/groups/[groupId]/chat` | Group chat | Member, else 404 | 5 |
| `/groups/[groupId]/members` | Members | Member, else 404 | 5 |
| `/groups/[groupId]/challenges` | Challenge dashboard (`?status=active\|upcoming\|completed`) | Member, else 404 | 7 |
| `/groups/[groupId]/challenges/[challengeId]` | Challenge detail / participation / results | Member, else 404 | 7 |
| `/groups/[groupId]/itinerary` | Shared group itinerary | Member, else 404 | 5 (read) / 6 (edit) |
| `/groups/[groupId]/settings` | Group settings and administration | Group owner/admin (moderators: limited tabs), else 404 | 5 |
| `/tours/[tourId]` | Audio tour player | Session; premium tours need entitlement (server) | 6 |
| `/profile` | Own profile | — | 3 |
| `/profile/edit` | Edit profile | — | 3 |
| `/profile/connections` | Connections | — | 4 |
| `/profile/badges` | Badges | — | 7 |
| `/notifications` | Notification centre | — | 4 |
| `/membership` | Membership dashboard | — | 5 |
| `/membership/checkout` | Checkout hand-off (`?product=`) | Redirects to Stripe; never renders card fields | 5 |
| `/membership/success` | Payment confirmation (polls entitlements) | Missing `session_id` → `/membership` | 5 |
| `/settings` | Account settings | **Session** (reachable before onboarding) | 3 |
| `/settings/privacy` | Privacy settings | Session | 3 |
| `/settings/notifications` | Notification settings | Session | 4 |
| `/settings/sessions` | Signed-in devices | Session | 3 |
| `/settings/data` | Data export and account deletion | Session | 9 |

### 2.4 Admin — `admin` (not indexable)

Every route renders **Dyn+Client** and requires **Staff** (`ADMIN_ACCESS`). Non-staff and anonymous requests both get **404** (§3). Responses are `noindex,nofollow` with `Cache-Control: private, no-store`. The **Permission** column names the platform permission from [03 §4](03-roles-permissions.md#4-platform-roles-staff) that gates the page. A staff member without it also gets **404**. The backend re-checks it on every call. PRD references: ADM-001…006.

| Route | Page | Permission to view (actions) | Phase |
|---|---|---|---|
| `/admin` | Overview metrics and operational alerts | `ADMIN_ACCESS`. Metric tiles filtered by `METRICS_READ` (support: operational only; moderator: moderation metrics only) | 8 |
| `/admin/users` | User search | `USERS_READ_BASIC` | 8 |
| `/admin/users/[userId]` | Account detail, suspension, moderation history | `USERS_READ_BASIC` (PII reveal: `USERS_READ_PII` with reason; actions: `USERS_SUSPEND`, `USERS_DELETE`) | 8 |
| `/admin/reports` | Report queue | `REPORTS_READ` | 8 |
| `/admin/reports/[reportId]` | Report review and action | `REPORTS_READ` (actions: `MODERATION_ACTION`) | 8 |
| `/admin/appeals` | Moderation appeals | `APPEALS_DECIDE` | 8 |
| `/admin/groups` | Groups under review | `REPORTS_READ` | 8 |
| `/admin/groups/[groupId]` | Group investigation, suspension | `REPORTS_READ` (actions: `GROUPS_SUSPEND`) | 8 |
| `/admin/challenges` | Flagged challenges and submissions | `CHALLENGES_REVIEW` | 8 |
| `/admin/challenges/disputes` | Prize disputes | `CHALLENGES_REVIEW` (fulfilment: `REWARDS_FULFIL`) | 8 |
| `/admin/destinations` | Destination catalog | `DESTINATIONS_EDIT` | 8 |
| `/admin/destinations/new` | Create destination | `DESTINATIONS_EDIT` | 8 |
| `/admin/destinations/[destinationId]` | Edit destination, localizations, featured placement | `DESTINATIONS_EDIT` | 8 |
| `/admin/guides` | Guide and audio content review | `GUIDES_EDIT` | 8 |
| `/admin/billing` | Subscriptions | `BILLING_READ` | 8 |
| `/admin/billing/entitlements` | Entitlement mappings | `BILLING_READ` (edit: `BILLING_CONFIGURE`) | 8 |
| `/admin/billing/events` | Billing events and payment failures | `BILLING_READ` | 8 |
| `/admin/audit` | Audit log viewer | `AUDIT_READ` | 8 |

03 has no read-only catalog permission and no group-investigation permission, so this table gates them on `DESTINATIONS_EDIT` and `REPORTS_READ`. See §9 Q6.

### 2.5 BFF route handlers — `apps/web/src/app/api/` (never indexed)

| Route | Methods | CSRF | Notes |
|---|---|---|---|
| `/api/auth/login` | GET | `state` + PKCE | `?intent=login\|signup&provider=google\|apple\|email&next=`. `next` is validated (§3.3). |
| `/api/auth/callback` | GET | `state` | OIDC callback. Errors go to `/login?error=<code>`. |
| `/api/auth/dev` | POST | Double-submit | 404 unless `DevIdentityProvider` is active |
| `/api/auth/logout` | POST | Double-submit | Clears `tb_session` and `tb_csrf`. Redirects to `/` (or the IdP end-session endpoint). |
| `/api/auth/session` | GET | — | `ViewerSummary` or `204` |
| `/api/v1/[...path]` | GET, POST, PUT, PATCH, DELETE | Double-submit on non-safe methods | Authenticated proxy (ADR-0011) |
| `/api/realtime/ticket` | POST | Double-submit | ADR-0013 |
| `/api/health` | GET | — | Liveness only. Never reveals configuration. |

All `/api/*` responses carry `X-Robots-Tag: noindex` and `Cache-Control: private, no-store` (except `/api/health`: `no-store`). `robots.txt` disallows `/api/`.

### 2.6 Canonical and duplicate-content rules

| Content | Rule |
|---|---|
| Static and catalog pages (`/`, destinations, guides, pricing, legal, about, download) | Self-referencing canonical **per locale**, plus `hreflang` alternates for all five locales and `x-default` → `en`. |
| Query-string variants (filters, `q`, `cursor`, `sort`, UTM) | Canonical = the path without query. Filtered views are `noindex,follow`. |
| Public stories | User content is not translated (01 §12), so the five locale variants would duplicate the body. Canonical = the variant whose locale matches the post's `language` (`pt` → `/pt-br/…`; unsupported languages → `en`). No `hreflang` alternates. The sitemap lists the canonical URL only. |
| Public profiles | Canonical = the `en` (unprefixed) variant. No `hreflang`. |
| Destination slugs | Canonical uses the catalog slug path. Old slugs 308-redirect to the current path (see §9 Q4). |
| Trailing slash | None. `/destinations/brazil/` → 308 → `/destinations/brazil`. |
| Case | Paths are lower-case. Mixed-case requests 308 to lower-case, except `[storyId]`, `[handle]`, `[guideId]` (IDs are lower-case UUIDv7 per doc 02 §5 anyway). |

## 3. Redirect and gating rules

### 3.1 Evaluation order

`proxy.ts` (cheap checks that use cookie *presence* only) runs first. Then layouts (checks that need the platform API) run in this order:

| # | Where | Condition | Action | Status |
|---|---|---|---|---|
| 1 | proxy | Path is `/api/*`, `/_next/*`, or a static file (`robots.txt`, `sitemap*.xml`, `manifest.webmanifest`, icons) | Skip locale and auth handling | — |
| 2 | proxy | Locale prefix is `/en` | Strip it: `/en/x` → `/x` | 308 |
| 3 | proxy | Locale prefix is a case variant (`/pt-BR`, `/PT-BR`, `/ES`) | Normalize: → `/pt-br/x`, `/es/x` | 308 |
| 4 | proxy | Unprefixed request, no `NEXT_LOCALE` cookie, `Accept-Language` prefers a supported non-default locale | Redirect to the prefixed path. Crawlers send no `Accept-Language` and get `en`. | 307 |
| 5 | proxy | `ADMIN_ALLOWED_HOSTS` is set and `/admin/**` is requested on another host | Rewrite to not-found | 404 |
| 6 | proxy | `tb_session` present and path is `/` | → `/feed` | 307 |
| 7 | proxy | `tb_session` present and path is `/login` or `/register` | → validated `next`, else `/feed` | 307 |
| 8 | proxy | `tb_session` **absent** and path is in `(traveler)` | → `/login?next=<path+query>` | 307 |
| 9 | proxy | `tb_session` **absent** and path is `/admin/**` | Rewrite to not-found (no login prompt, so admin is not advertised; staff use `/login?next=/admin`) | 404 |
| 10 | proxy | Access token expires in < 60 s | Refresh and rewrite cookies (ADR-0011). On refresh failure, clear `tb_session` and apply rule 8 or 9. | — |
| 11 | traveler layout | `GET /v1/users/me` → `401` | Clear the cookie (via a route handler) → `/login?next=` | 307 |
| 12 | traveler layout | `onboarding_completed = false` and path is not `/onboarding` or `/settings/**` | → `/onboarding?next=<path>` | 307 |
| 13 | `/onboarding` page | `onboarding_completed = true` | → `/feed` | 307 |
| 14 | traveler layout | `account_status = suspended` (normally caught at login with `account_suspended`, 03 §6) | Clear the session → `/login?error=account_suspended` (shows the appeal path) | 307 |
| 14a | traveler layout | `account_status = restricted` or `deletion_pending` | Render normally with a shell banner: the restriction and its end date, or the deletion date with "Cancel deletion" (AUTH-010). Write controls follow 03 §6. | 200 |
| 15 | admin layout | `roles` contains no platform role | `notFound()` | 404 |
| 16 | admin page | Staff without the page permission (03) | `notFound()` | 404 |
| 17 | resource pages | API returns `404` for a hidden resource (private group, blocked profile, a conversation you are not in, a non-public story) | `notFound()`, the same page as a missing resource | 404 |
| 18 | `/membership/success` | No `session_id` query | → `/membership` | 307 |
| 19 | signed-in `preferred_language` ≠ URL locale | First navigation after login only (flag in session) | Redirect once to the preferred locale | 307 |

Redirects use **307/308** so methods are preserved. Permanent (308) is used only for canonicalization rules 2–3 and §2.6.

### 3.2 Not-found and error surfaces

* One localized `not-found.tsx` per layout group. It has no information about *why* (hidden or missing is indistinguishable) and sends `noindex`.
* `error.tsx` per group shows an `ErrorState` with retry and the `request_id` reference (04).
* Auth errors from the IdP land on `/login?error=<code>`. Known codes: `access_denied`, `state_mismatch`, `idp_unavailable`, `account_suspended`, `age_restricted`. Each maps to a localized message.

### 3.3 `next` parameter validation (open-redirect prevention)

`next` is accepted only if it:
1. is a relative path starting with a single `/` (not `//`, `/\`, or a scheme);
2. resolves on the same origin after URL parsing;
3. is not under `/api/`, `/dev/` or `/login`/`/register`;
4. is at most 512 characters.

Anything else is replaced with `/feed`.

## 4. Locale prefix rules

| Locale | Code | URL prefix | `<html lang>` | `dir` | `hreflang` |
|---|---|---|---|---|---|
| English (default) | `en` | *(none)* | `en` | `ltr` | `en`, also `x-default` |
| Spanish | `es` | `/es` | `es` | `ltr` | `es` |
| Brazilian Portuguese | `pt-BR` | `/pt-br` | `pt-BR` | `ltr` | `pt-BR` |
| French | `fr` | `/fr` | `fr` | `ltr` | `fr` |
| German | `de` | `/de` | `de` | `ltr` | `de` |

* next-intl `localePrefix: { mode: 'as-needed', prefixes: { 'pt-BR': '/pt-br' } }`. The registry lives in `@travelbuddy/i18n` and carries `dir` for future RTL locales.
* **Pathnames are not localized in v1.** `/es/destinations/brazil/rio-de-janeiro` uses the same ASCII catalog slugs in every locale. Localized pathnames can be added later; doing so would require 308s from the old paths.
* **Detection order:** URL prefix → `NEXT_LOCALE` cookie (set by `LocaleSwitcher`) → `Accept-Language` (unprefixed requests only) → `en`. IP-based detection is never used (01 §12).
* `LocaleSwitcher` keeps the current path and query and changes only the prefix. On public pages it is a plain link, so it works without JavaScript.
* BFF and API routes are locale-less. The browser sends `Accept-Language` from the active locale, and the BFF forwards it to the platform.
* Adding a locale needs a registry entry, a message catalog (which passes the key-parity test), and sitemap alternates (generated from the registry). No route changes are needed.

## 5. Navigation model

### 5.1 Breakpoints

From [04 §6](04-design-system.md#6-breakpoints-and-layout): `sm` 640 · `md` 768 · `lg` 1024 · `xl` 1280 · `2xl` 1536. "Mobile" means < 768, "tablet" 768–1023, "desktop" ≥ 1024.

### 5.2 Public site (`(marketing)`)

| Element | Desktop ≥ lg | Tablet md–lg | Mobile < md |
|---|---|---|---|
| **SiteHeader** | Sticky. Transparent over the homepage and destination heroes, solid surface after 48 px scroll. Left: logo. Centre: Destinations · Stories · Plan with AI (`/#ai-planner`) · Companions (`/#companions`) · Pricing. Right: LocaleSwitcher, ThemeToggle, "Log in" (ghost), "Join free" (accent). | Same, but centre links collapse into a "Menu" Sheet (start side) | Logo + "Join free" + menu button. The Sheet holds all links, LocaleSwitcher, ThemeToggle and Log in. |
| **Hero search** | DestinationAutocomplete inline in the hero | Same | Full-width; opens a full-screen search Sheet on focus |
| **SiteFooter** | Four columns: Explore (Destinations, Stories, Guides) · Product (AI planner, Companions, Groups, Audio guides, Pricing, Download) · Company (About) · Legal (Terms, Privacy, Cookies, Community guidelines). Then app-store badges, LocaleSwitcher and copyright. | Two columns | Accordion sections |
| **Skip link** | "Skip to content" as the first focusable element | Same | Same |

### 5.3 Traveler app (`(traveler)`)

| Element | Desktop ≥ xl (1280+) | Desktop lg–xl (1024–1279) and tablet md–lg | Mobile < md |
|---|---|---|---|
| **Primary navigation** | **TravelerSidebar** expanded, 264 px: Home (`/feed`), Explore, My Trips, Companions, Groups, Messages (unread badge), Profile. Below them: "Create post" (primary button), then Saved, Notifications, Settings. The footer shows the membership state (Free / Premium). | **TravelerSidebar** as a 72 px icon rail with tooltips and labels exposed to assistive tech. A toggle expands it as an overlay. | **MobileBottomNav**, 5 items: Home, Explore, Trips, Messages (badge), Profile. Companions, Groups, Saved, Notifications, Membership and Settings live in the "More" menu in the top bar. |
| **Top bar** | Destination search · AI assistant trigger (sparkles) · notifications bell (badge) · avatar menu (Profile, Membership, Settings, Theme, Language, Log out) | Same | Compact app bar: page title, assistant trigger, notifications, "More" menu |
| **Create post** | Sidebar button opens the `/posts/new` modal (intercepted route) | Rail button | Floating action button on `/feed` and `/profile`, above the bottom nav; opens `/posts/new` full-screen |
| **AI assistant** | Right-side Sheet, 420 px, non-modal on ≥ xl | Modal Sheet | Full-screen Sheet |
| **Messages** | Persistent two-pane layout: ConversationList (320 px) + MessageThread | Two-pane on lg; list-or-thread on md | List-or-thread. The bottom nav hides inside an open thread so the composer gets the space. |
| **Group detail** | Tabs (Overview, Chat, Members, Challenges, Itinerary) as a horizontal tab bar under GroupHeader | Same | Scrollable tab bar; chat opens full-screen |
| **Environment banner** | EnvironmentBanner above everything when `TB_API_MODE=mock` or `APP_ENV ≠ production` | Same | Same (compact) |

Active state uses `aria-current="page"`. Every navigation item has a visible label, or on the rail a tooltip plus an accessible name. Unread badges announce counts ("Messages, 3 unread").

### 5.4 Admin (`admin`)

| Element | Desktop ≥ lg | < lg |
|---|---|---|
| **AdminSidebar** | Always expanded, 248 px, grouped: **Overview** · **Trust & safety** (Reports, Appeals, Users, Groups, Challenges) · **Content** (Destinations, Guides) · **Revenue** (Billing, Entitlements, Billing events) · **Compliance** (Audit log). Items the viewer's permissions (03) do not allow are not rendered. | Drawer from the menu button |
| **Top bar** | Environment label (Production / Staging / Mock, colour-coded) · global user search (`users.read`) · "Back to app" · avatar menu | Same |
| **Supported widths** | Optimized for ≥ 1280. Fully functional at 768. Usable at 360 for urgent moderation. | — |

Admin never shows the traveler navigation, the AI assistant or create-post entry points.

## 6. XML sitemap design

### 6.1 Structure

```
/robots.txt
  Sitemap: https://<host>/sitemap.xml
/sitemap.xml                         sitemap index
  /sitemaps/static.xml               home, directory, stories index, guides index, pricing,
                                     download, about, legal — every locale + hreflang
  /sitemaps/destinations-{n}.xml     countries + cities (+ attractions from Phase 6),
                                     every locale + hreflang; chunks of ≤ 10,000 <url>
  /sitemaps/stories-{n}.xml          public stories, canonical URL only; ≤ 10,000 per chunk,
                                     newest first
  /sitemaps/guides.xml               published guides, every locale + hreflang (Phase 6)
  /sitemaps/profiles.xml             public profiles whose owners opted in to indexing (Phase 3)
```

* Generated by Next.js metadata routes (`sitemap.ts` with `generateSitemaps()`, or route handlers for the index) from platform list endpoints: `GET /v1/destinations?published=true`, `GET /v1/public/posts`, `GET /v1/guides`. Responses are cached `s-maxage=3600`, and the stories chunks `s-maxage=600`.
* Each `<url>` carries `<loc>`, `<lastmod>` (the resource's `updated_at`) and, for translatable pages, `<xhtml:link rel="alternate" hreflang="…">` for all five locales plus `x-default`. No `priority` or `changefreq`, because search engines ignore them.
* Chunk size is 10,000 URLs (well under the 50,000 / 50 MB protocol limit) to keep generation time and memory bounded.
* Production only. Non-production environments serve `robots.txt` with `Disallow: /`, no sitemap, and a global `X-Robots-Tag: noindex`.

### 6.2 Inclusion and exclusion

| Included | Excluded |
|---|---|
| Published destinations above the content threshold (07) | Unpublished or below-threshold destinations (served `noindex` until enriched) |
| Public stories: `visibility = public`, moderation `approved`, author not suspended, not deleted | Followers-only, connections-only and private posts (POST-008); removed, deleted or under-review posts; posts by suspended or deleted accounts |
| Public profiles with explicit search-engine consent | All other profiles |
| Guides with a published description | Premium audio assets themselves (audio URLs are never in sitemaps) |
| Static marketing and legal pages | Everything in `(auth)`, `(traveler)`, `admin` and `/api` |
| — | Filter, search, pagination (`?cursor=`) and tracking-parameter URLs |
| — | `/dev/login` and any environment-specific routes |

Removal latency: when a story becomes non-public, it must disappear from both the page and the sitemap. The page purge is §9 Q1. Sitemaps regenerate within 10 minutes.

### 6.3 `robots.txt` (production)

```
User-agent: *
Allow: /
Disallow: /api/
Disallow: /admin
Disallow: /dev/
Disallow: /*/admin
Disallow: /*/dev/
Sitemap: https://<host>/sitemap.xml
```

Traveler routes are **not** listed in `robots.txt`. They already redirect anonymous crawlers to `/login` (which is `noindex`) and send `noindex`. Listing them would add nothing, and blocking them would stop crawlers from seeing the `noindex`.

## 7. Human-readable sitemap

```
Travel Buddy (web)
├── Home  /
├── Destinations  /destinations
│   └── {Country}  /destinations/{country}
│       └── {City}  /destinations/{country}/{city}
│           └── {Attraction}  …/attractions/{place}            (Phase 6)
├── Stories  /stories
│   └── {Story}  /stories/{storyId}
├── Guides  /guides                                            (Phase 6)
│   └── {Guide}  /guides/{guideId}
├── Pricing  /pricing
├── Download the app  /download
├── About  /about
├── Legal
│   ├── Terms  /legal/terms
│   ├── Privacy  /legal/privacy
│   ├── Cookies  /legal/cookies
│   └── Community guidelines  /legal/community-guidelines
├── People  /u/{handle}                                        (public profiles, Phase 3)
│
├── Account access (not indexed)
│   ├── Log in  /login
│   ├── Create account  /register
│   ├── Forgot password  /forgot-password
│   ├── Verify email  /verify-email
│   └── Onboarding  /onboarding
│
├── Traveler app (signed in, not indexed)
│   ├── Home feed  /feed
│   ├── Posts  /posts/new · /posts/{id} · /posts/{id}/edit
│   ├── Explore  /explore
│   ├── Saved  /saved
│   ├── AI assistant  /assistant
│   ├── My trips  /trips · /trips/new · /trips/{id}
│   ├── Companions  /companions · /companions/requests
│   ├── Messages  /messages · /messages/{conversationId}
│   ├── Groups  /groups · /groups/discover · /groups/invitations · /groups/new
│   │   └── {Group}  /groups/{id} · /chat · /members · /challenges[/{challengeId}] · /itinerary · /settings
│   ├── Audio tour  /tours/{tourId}
│   ├── Profile  /profile · /profile/edit · /profile/connections · /profile/badges
│   ├── Notifications  /notifications
│   ├── Membership  /membership · /membership/checkout · /membership/success
│   └── Settings  /settings · /privacy · /notifications · /sessions · /data
│
└── Admin (staff, not indexed)  /admin
    ├── Users  /admin/users · /admin/users/{id}
    ├── Reports  /admin/reports · /admin/reports/{id}
    ├── Appeals  /admin/appeals
    ├── Groups  /admin/groups · /admin/groups/{id}
    ├── Challenges  /admin/challenges · /admin/challenges/disputes
    ├── Destinations  /admin/destinations · /new · /{id}
    ├── Guides  /admin/guides
    ├── Billing  /admin/billing · /entitlements · /events
    └── Audit log  /admin/audit
```

## 8. File-system mapping (App Router)

```text
apps/web/src/app/
  [locale]/
    layout.tsx                       html/body, fonts, providers, theme script
    not-found.tsx
    (marketing)/layout.tsx           SiteHeader + SiteFooter
      page.tsx                       /
      destinations/page.tsx
      destinations/[country]/page.tsx
      destinations/[country]/[city]/page.tsx
      destinations/[country]/[city]/attractions/[place]/page.tsx
      stories/page.tsx · stories/[storyId]/page.tsx
      u/[handle]/page.tsx
      guides/page.tsx · guides/[guideId]/page.tsx
      pricing/page.tsx · download/page.tsx · about/page.tsx
      legal/{terms,privacy,cookies,community-guidelines}/page.tsx
    (auth)/layout.tsx                minimal brand layout
      login/ register/ forgot-password/ verify-email/ onboarding/ dev/login/
    (traveler)/layout.tsx            session + onboarding gate, TravelerSidebar, MobileBottomNav
      feed/ posts/ explore/ saved/ assistant/ trips/ companions/ messages/
      groups/ tours/ profile/ notifications/ membership/ settings/
      @modal/(.)posts/new/page.tsx   intercepted composer modal
    admin/layout.tsx                 staff gate, AdminSidebar
      page.tsx users/ reports/ appeals/ groups/ challenges/ destinations/ guides/ billing/ audit/
  api/
    auth/{login,callback,dev,logout,session}/route.ts
    v1/[...path]/route.ts
    realtime/ticket/route.ts
    health/route.ts
  robots.ts
  sitemap.xml/route.ts               index
  sitemaps/[name]/route.ts           child sitemaps
  manifest.ts
apps/web/src/proxy.ts                rules §3.1 #1–#10
```

## 9. Open questions

| # | Question | Proposed resolution |
|---|---|---|
| Q1 | **Story privacy vs ISR.** 01 §5 caches story pages for 10 min, but a post that becomes private or deleted must stop being public at once (brief §6). 01 §10.5 lists no revalidation endpoint. | Add a BFF handler `POST /api/revalidate` that accepts a signed (HMAC, shared secret) call from the platform's outbox relay on `PostRemoved` / visibility change / `UserDeactivated`. It calls `revalidateTag('post:{id}')` and purges the CDN path. Until then, use `revalidate = 60` for `/stories/[storyId]`. Needs a doc 02 subscriber and a 06 entry. |
| Q2 | **Viewing other users' profiles when signed in.** `/u/[handle]` is public and cannot read cookies, but connection-only profiles and block rules apply to signed-in viewers. | Interim: render the anonymous projection server-side, and add a client island that fetches `GET /v1/users/{userId}` (+ `/relationship`) via the BFF for relationship controls and connection-only fields (05 §P-08). Recommended: add an authenticated route `/people/[handle]` in `(traveler)` and make in-app links use it. |
| Q3 | **Appeals have no traveler-side route.** Suspended users are signed out (rule 14), and restricted users and authors of removed content need a way to appeal (03 §8). | Add `/settings/appeals` (Session, Phase 8) or link to a help-centre form. Product to decide. |
| Q4 | **Slug history.** Renaming a destination slug breaks indexed URLs unless the platform keeps old slugs. | `GET /v1/destinations/lookup?path=` returns `{redirect_to}` for retired slugs, and the page issues a 308. Needs a backend `destination_slug_history` table. |
| Q5 | **Story canonical locale** (§2.6) must match [07 — SEO strategy](07-seo-strategy.md). | 07 to confirm. If 07 differs, 07 wins and this table is updated. |
| Q6 | **Admin permissions without a 03 key.** 03 §4 has no read-only catalog permission and no group-investigation permission. §2.4 uses `DESTINATIONS_EDIT` and `REPORTS_READ`. | 03 to add `DESTINATIONS_READ` / `GROUPS_INVESTIGATE`, or confirm the mapping. |
| Q7 | **`/groups/discover` vs the PRD.** PRD §1.2 makes public group discovery a v1 non-goal, and GRP-004 makes v1 groups private and invite-only (public/unlisted behind flags). | Ship the route behind flag `groups.public_discovery`. With the flag off, the route returns 404 and the nav item is hidden. 01 §10.3 to note the flag. |
| Q8 | **Guest content cap vs story sitemap.** AUTH-012 caps the guest public feed at 20 posts, while §6 lists every public story in sitemaps. | The cap applies to the anonymous list endpoints (`/stories`, destination story rails). Individual `/stories/[storyId]` pages stay reachable and indexable. The PRD owner should confirm. |
