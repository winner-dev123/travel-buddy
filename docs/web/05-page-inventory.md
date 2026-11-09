# Web 05 — Page and Screen Inventory

| | |
|---|---|
| **Status** | Draft v1.0 — Web Phase 1 |
| **Covers** | Required output #7: for every page, its purpose, interactions, components, API dependencies, loading/error/empty states, authorization and acceptance criteria |
| **Anchor** | [Web 01](01-architecture.md) §10 (routes), §11 (API surface) · [02 — Routes & sitemap](02-routes-and-sitemap.md) · [03 — Roles & permissions](03-roles-permissions.md) · [04 — Design system](04-design-system.md) |
| **Product source** | [PRD](../01-prd.md) requirement IDs (`AREA-NNN`) · [07 — Entitlements](../07-subscription-entitlement-policy.md) · [08 — Threat model](../08-privacy-security-threat-model.md) |

---

## 0. How to read this document

* **Phase** is the *web* phase (brief §31, 01 §10). PRD phases differ and are not used here. PRD requirement IDs are cited wherever a page implements a requirement; tests carry them as `/* req: AREA-NNN */`.
* **Components** use the names in [04 §11](04-design-system.md#11-component-inventory).
* **API** lists platform endpoints the page calls (through the BFF for client code, directly for Server Components). Paths come from 01 §11 plus the contract decisions agreed with the backend stream (§1.5). Sub-resource paths marked *(ind.)* are indicative; [06 — API integration](06-api-integration.md) and `contracts/openapi` are authoritative.
* **Authorization** uses the vocabulary of [02 §1](02-routes-and-sitemap.md#1-legend) (Public, Guest, Session, Onboarded, Staff) and [03 §3](03-roles-permissions.md#3-how-the-web-reflects-a-decision) (show, hide, disable+why, upsell, gate→login, 404). The web check is always defence in depth; the backend decides.
* Page IDs are `P-<phase>.<n>`. They are stable; new pages get new numbers.

## 1. Global conventions (apply to every page unless the page says otherwise)

### 1.1 Loading

| Situation | Treatment |
|---|---|
| First render of server-rendered public pages | No loading UI. HTML arrives complete (ISR). Client islands (Save, Connect, current plan) render a neutral placeholder of the final size, which avoids CLS. |
| Route transition in the traveler app and admin | `loading.tsx` per segment with a Skeleton that matches the final layout (cards, rows, header). The shell (navigation) stays mounted. |
| Data that loads in under ~300 ms | No spinner flash: show skeletons only after 150 ms. |
| Mutations | Button `L` state (label kept, `aria-busy`). Optimistic UI only for idempotent toggles (01 §9). |
| Paging | `InfiniteSentinel` plus visible "Load more". A row of skeleton cards is appended while fetching. |

### 1.2 Errors (by problem `code`; never by message text)

| Code / status | Treatment |
|---|---|
| Network failure / `5xx` / `service_unavailable` | `ErrorState` (inline or page) with Retry and "Reference: {request_id}" |
| `401 unauthenticated` / `token_expired` after refresh | Session ended → `/login?next=` (02 §3.1 rule 11) |
| `404 not_found` on the page's main resource | `notFound()`, the same page for missing and hidden (doc 02 §5) |
| `403 forbidden` | 403 page only where existence is already known (03 §3) |
| `403 entitlement_required` | `EntitlementGate` upsell naming the `entitlement` (07 §7) |
| `429 quota_exceeded` | Quota message with `limit` and `resets_at` (07 §7); premium users see the reset date, free users see an upsell |
| `429 rate_limited` | "Too many attempts. Try again in {Retry-After}" with the control disabled until then |
| `403 email_unverified` (AUTH-004) | Inline banner "Verify your email to {action}" + "Resend email" |
| `422 validation_failed` | Field errors mapped from `errors[].field` onto `FormField`; focus moves to the first invalid field |
| `409 conflict` / `412 precondition_failed` | "This was changed elsewhere": reload the latest version, and keep the user's unsaved input visible to re-apply |
| `503 feature_not_available_in_mock` | Honest "Not available in this environment" panel, never a fake result (01 §7.1 rule 5). It applies to payments, AI generation, live device location and realtime chat delivery. |

### 1.3 Empty states

Always an `EmptyState` with a headline, one sentence, and a primary action that moves the user forward. Never a bare "No data". Where FEED-001 guarantees content, an empty state is a defect, not a design.

### 1.4 Global acceptance criteria (G-AC)

Every page also meets these. They are not repeated per page.

1. **G-AC-1 i18n:** all strings come from `@travelbuddy/i18n`; the page renders correctly in en, es, pt-BR, fr and de; dates, numbers and currency use locale formatters (I18N-001/002).
2. **G-AC-2 a11y:** axe reports zero serious or critical violations; every task can be completed with the keyboard alone; focus order follows visual order; headings form a valid outline (NFR-008).
3. **G-AC-3 responsive:** no horizontal scroll from 320 px to 2560 px; touch targets ≥ 44 px; layout follows [04 §6.1](04-design-system.md#61-responsive-behaviour-per-device-class-brief-5).
4. **G-AC-4 robots and caching:** headers and meta follow [02 §2](02-routes-and-sitemap.md#2-route-map) exactly; traveler and admin responses are `private, no-store`.
5. **G-AC-5 privacy:** no other user's email, birth data, coordinates or distance appears in the DOM or in any response the page receives (PROF-005, LOC-009).
6. **G-AC-6 themes:** correct in light, dark and system themes, with no flash of the wrong theme.
7. **G-AC-7 RTL readiness:** with a pseudo-RTL locale in tests, the layout mirrors with no overlapping or clipped content (I18N-004).
8. **G-AC-8 performance:** meets the budgets in 01 §15 for its area.
9. **G-AC-9 mock honesty:** in mock mode the EnvironmentBanner is visible, and no feature listed in 01 §7.1 rule 5 shows a simulated success.

### 1.5 Contract decisions used throughout (agreed with the backend stream)

| Topic | Contract |
|---|---|
| Entitlements | `GET /v1/billing/entitlements` (07 §7). Feature keys `groups.create`, `challenges.create`, `guides.premium`, `audio_tours.premium`, `ai.trip_replan`. Quotas `ai.itinerary_generations`, `ai.trip_replans`, `offline.packages`, `groups.owned`. |
| Reactions | `POST /v1/posts/{id}/reactions {reaction}` sets or replaces the viewer's single reaction (`like`, `love`, `helpful`, `wow`). `DELETE /v1/posts/{id}/reactions/me` clears it (POST-005). |
| Browse destination | `PUT /v1/users/me/browse-destination {destination_id}` (LOC-002) |
| Feed context | The feed response carries `context.source ∈ gps \| selected \| upcoming_trip \| interests \| global \| following` and `context.destination` |
| Public stories | `GET /v1/public/posts[/{id}]` returns `PublicPost`, only for `visibility = public` **and** moderation `approved` |
| Registration | `POST /v1/auth/register` with the IdP ID token, `client: "web"`, `birth_date` (18+ gate; under 18 → `age_restricted`, AUTH-008), and acceptance of the terms and privacy versions (AUTH-009) |
| Dev login | `POST /v1/dev/idp/token {sub, email, name}` → dev ID token → normal `POST /v1/auth/login` / `register` (ADR-0011) |

## 2. Index

| ID | Route | Page | Phase |
|---|---|---|---|
| [S-1.1](#s-11-public-shell) | `(marketing)` layout | Public shell | 1 |
| [S-1.2](#s-12-traveler-shell) | `(traveler)` layout | Traveler shell | 1 |
| [S-1.3](#s-13-admin-shell) | `admin` layout | Admin shell | 1 |
| [P-1.1](#p-11-login) | `/login` | Log in | 1 |
| [P-1.2](#p-12-register) | `/register` | Create account | 1 |
| [P-1.3](#p-13-forgot-password) | `/forgot-password` | Forgot password | 1 |
| [P-1.4](#p-14-verify-email) | `/verify-email` | Verify email | 1 |
| [P-1.5](#p-15-devlogin) | `/dev/login` | Development persona picker | 1 |
| [P-2.1](#p-21-homepage) | `/` | Homepage | 2 |
| [P-2.2](#p-22-destinations-directory) | `/destinations` | Destinations directory | 2 |
| [P-2.3](#p-23-country-page) | `/destinations/[country]` | Country page | 2 |
| [P-2.4](#p-24-destination-page) | `/destinations/[country]/[city]` | Destination page | 2 |
| [P-2.5](#p-25-public-stories-index) | `/stories` | Public stories index | 2 |
| [P-2.6](#p-26-public-story) | `/stories/[storyId]` | Public story | 2 |
| [P-2.7](#p-27-pricing) | `/pricing` | Pricing | 2 / 5 |
| [P-2.8](#p-28-download) | `/download` | Download the app | 2 |
| [P-2.9](#p-29-about) | `/about` | About | 2 |
| [P-2.10](#p-210-legal-pages) | `/legal/terms`, `/legal/privacy`, `/legal/cookies`, `/legal/community-guidelines` | Legal pages | 2 |
| [P-3.1](#p-31-onboarding) | `/onboarding` | Onboarding | 3 |
| [P-3.2](#p-32-home-feed) | `/feed` | Home feed | 3 |
| [P-3.3](#p-33-post-composer) | `/posts/new` | Post composer | 3 |
| [P-3.4](#p-34-post-detail) | `/posts/[postId]` | Post detail | 3 |
| [P-3.5](#p-35-edit-post) | `/posts/[postId]/edit` | Edit post | 3 |
| [P-3.6](#p-36-saved) | `/saved` | Saved | 3 / 6 |
| [P-3.7](#p-37-own-profile) | `/profile` | Own profile | 3 |
| [P-3.8](#p-38-edit-profile) | `/profile/edit` | Edit profile | 3 |
| [P-3.9](#p-39-public-profile) | `/u/[handle]` | Public profile | 3 |
| [P-3.10](#p-310-account-settings) | `/settings` | Account settings | 3 |
| [P-3.11](#p-311-privacy-settings) | `/settings/privacy` | Privacy settings | 3 |
| [P-3.12](#p-312-sessions) | `/settings/sessions` | Signed-in devices | 3 |
| [P-4.1](#p-41-companion-discovery) | `/companions` | Companion discovery | 4 |
| [P-4.2](#p-42-connection-requests) | `/companions/requests` | Connection requests | 4 |
| [P-4.3](#p-43-connections) | `/profile/connections` | Connections | 4 |
| [P-4.4](#p-44-messages) | `/messages` | Messages | 4 |
| [P-4.5](#p-45-conversation) | `/messages/[conversationId]` | Conversation | 4 |
| [P-4.6](#p-46-notifications) | `/notifications` | Notifications | 4 |
| [P-4.7](#p-47-notification-settings) | `/settings/notifications` | Notification settings | 4 |
| [P-5.1](#p-51-membership) | `/membership` | Membership dashboard | 5 |
| [P-5.2](#p-52-checkout-hand-off) | `/membership/checkout` | Checkout hand-off | 5 |
| [P-5.3](#p-53-payment-confirmation) | `/membership/success` | Payment confirmation | 5 |
| [P-5.4](#p-54-my-groups) | `/groups` | My groups | 5 |
| [P-5.5](#p-55-discover-groups) | `/groups/discover` | Discover groups (flagged) | 5 |
| [P-5.6](#p-56-group-invitations) | `/groups/invitations` | Group invitations | 5 |
| [P-5.7](#p-57-create-group) | `/groups/new` | Create group | 5 |
| [P-5.8](#p-58-group-overview) | `/groups/[groupId]` | Group overview | 5 |
| [P-5.9](#p-59-group-chat) | `/groups/[groupId]/chat` | Group chat | 5 |
| [P-5.10](#p-510-group-members) | `/groups/[groupId]/members` | Group members | 5 |
| [P-5.11](#p-511-group-itinerary) | `/groups/[groupId]/itinerary` | Shared group itinerary | 5 / 6 |
| [P-5.12](#p-512-group-settings) | `/groups/[groupId]/settings` | Group settings | 5 |
| [P-6.1](#p-61-ai-assistant) | `/assistant` | AI assistant | 6 |
| [P-6.2](#p-62-my-trips) | `/trips` | My trips | 6 |
| [P-6.3](#p-63-create-trip) | `/trips/new` | Create trip | 6 |
| [P-6.4](#p-64-trip-detail) | `/trips/[tripId]` | Trip detail & itinerary | 6 |
| [P-6.5](#p-65-explore) | `/explore` | Explore | 6 |
| [P-6.6](#p-66-attraction-page) | `/destinations/[country]/[city]/attractions/[place]` | Attraction page | 6 |
| [P-6.7](#p-67-guide-library) | `/guides` | Guide library | 6 |
| [P-6.8](#p-68-guide-detail) | `/guides/[guideId]` | Guide detail | 6 |
| [P-6.9](#p-69-audio-tour-player) | `/tours/[tourId]` | Audio tour player | 6 |
| [P-7.1](#p-71-challenge-dashboard) | `/groups/[groupId]/challenges` | Challenge dashboard | 7 |
| [P-7.2](#p-72-challenge-detail) | `/groups/[groupId]/challenges/[challengeId]` | Challenge detail | 7 |
| [P-7.3](#p-73-badges) | `/profile/badges` | Badges | 7 |
| [P-8.1](#p-81-admin-overview) | `/admin` | Admin overview | 8 |
| [P-8.2](#p-82-user-search) | `/admin/users` | User search | 8 |
| [P-8.3](#p-83-user-detail) | `/admin/users/[userId]` | User detail | 8 |
| [P-8.4](#p-84-report-queue) | `/admin/reports` | Report queue | 8 |
| [P-8.5](#p-85-report-review) | `/admin/reports/[reportId]` | Report review | 8 |
| [P-8.6](#p-86-appeals) | `/admin/appeals` | Appeals | 8 |
| [P-8.7](#p-87-groups-under-review) | `/admin/groups` | Groups under review | 8 |
| [P-8.8](#p-88-group-investigation) | `/admin/groups/[groupId]` | Group investigation | 8 |
| [P-8.9](#p-89-challenge-review) | `/admin/challenges` | Challenge review | 8 |
| [P-8.10](#p-810-prize-disputes) | `/admin/challenges/disputes` | Prize disputes | 8 |
| [P-8.11](#p-811-destination-catalog) | `/admin/destinations` | Destination catalog | 8 |
| [P-8.12](#p-812-destination-editor) | `/admin/destinations/new`, `/admin/destinations/[destinationId]` | Destination editor | 8 |
| [P-8.13](#p-813-guide-review) | `/admin/guides` | Guide review | 8 |
| [P-8.14](#p-814-subscriptions) | `/admin/billing` | Subscriptions | 8 |
| [P-8.15](#p-815-entitlement-mappings) | `/admin/billing/entitlements` | Entitlement mappings | 8 |
| [P-8.16](#p-816-billing-events) | `/admin/billing/events` | Billing events | 8 |
| [P-8.17](#p-817-audit-log) | `/admin/audit` | Audit log | 8 |
| [P-9.1](#p-91-data-and-account-deletion) | `/settings/data` | Data export & account deletion | 9 |

---

## Phase 1 — Foundation

### S-1.1 Public shell

* **Purpose:** Consistent frame for all `(marketing)` pages, with header, footer, locale and theme controls, and a path into the app.
* **Interactions:** navigate main sections; switch locale (keeps path); switch theme; "Log in" / "Join free"; mobile menu Sheet; skip link.
* **Components:** SiteHeader, SiteFooter, LocaleSwitcher, ThemeToggle, EnvironmentBanner, Sheet, Container.
* **API:** none (static).
* **Loading / Error / Empty:** n/a (static). Root `error.tsx` uses ErrorState page variant; `not-found.tsx` is localized and `noindex`.
* **Authorization:** Public. Never reads cookies (01 §5), so signed-in state is not shown in the header; signed-in users are redirected off `/` by `proxy.ts` (02 §3.1 rule 6).
* **Acceptance criteria:**
  1. The header is transparent over heroes and turns solid after 48 px scroll, keeping ≥ 4.5:1 text contrast in both states.
  2. LocaleSwitcher links point to the same path under the target prefix and work with JavaScript disabled.
  3. The skip link is the first focusable element and moves focus to `<main>`.
  4. The public HTML contains no `Set-Cookie` and does not vary by cookie.

### S-1.2 Traveler shell

* **Purpose:** Authenticated frame: primary navigation, top bar, viewer context, global assistant and create-post entry points, account-state banners.
* **Interactions:** navigate Home (`/feed`), Explore, My Trips, Companions, Groups, Messages, Profile; open the "More" menu (mobile); create post; open the assistant; open notifications; avatar menu (profile, membership, settings, theme, language, log out).
* **Components:** TravelerSidebar, MobileBottomNav, top bar (DestinationAutocomplete, IconButton, DropdownMenu, Avatar), EnvironmentBanner, OnlineOnlyBadge, DiscoveryStatusIndicator (Phase 4), Toast viewport.
* **API:** `GET /v1/users/me` (server, per request: profile summary, roles, `account_status`, `onboarding_completed`, `email_verified`); `GET /v1/billing/entitlements` (plan badge, client); `GET /v1/notifications?unread=true` (badge, Phase 4); unread conversation counts via realtime (Phase 4).
* **Loading:** server-rendered navigation, with skeleton badges until counts arrive.
* **Error:** `users/me` failure renders a full-page ErrorState with Retry. `401` → `/login?next=`.
* **Empty:** n/a.
* **Authorization:** Session. Gates per 02 §3.1 rules 8, 11–14a: not onboarded → `/onboarding`; `suspended` → signed out; `restricted` / `deletion_pending` → banner (03 §6, AUTH-010). Log out is `POST /api/auth/logout` with the CSRF header.
* **Acceptance criteria:**
  1. Given an unauthenticated request to any traveler route, the response is a 307 to `/login?next=<path+query>`.
  2. Given `onboarding_completed=false`, any traveler route other than `/onboarding` and `/settings/**` redirects to `/onboarding`.
  3. The active item has `aria-current="page"`, and badge counts are part of the accessible name ("Messages, 3 unread").
  4. At < 768 px the bottom nav shows exactly Home, Explore, Trips, Messages, Profile, and Companions and Groups are reachable from "More".
  5. When offline, Feed, Companions, Messages and Assistant entries show "Online only" (OFF-003).
  6. Log out clears `tb_session` and `tb_csrf`, and the back button does not reveal cached private pages (`no-store`).

### S-1.3 Admin shell

* **Purpose:** Frame for staff tools, with navigation filtered by platform permissions.
* **Interactions:** navigate permitted sections; global user search (`USERS_READ_BASIC`); "Back to app"; environment label.
* **Components:** AdminSidebar, top bar, EnvironmentBanner, Badge (environment), DropdownMenu.
* **API:** `GET /v1/users/me` (roles); permissions resolved from roles per 03 §4 (or `GET /v1/admin/me/permissions` *(ind.)*).
* **Loading / Error / Empty:** as the traveler shell.
* **Authorization:** Staff (`ADMIN_ACCESS`). Anonymous and non-staff users get **404** (02 §3.1 rules 9, 15). Sections without permission are hidden, and direct navigation to them gives 404 (03 §4).
* **Acceptance criteria:**
  1. A traveler without platform roles requesting `/admin` or any sub-route gets HTTP 404 with the generic not-found page.
  2. A `support` user does not see Destinations, Guides, Entitlements or Audit in the nav, and gets 404 on direct navigation.
  3. Every admin response has `Cache-Control: private, no-store` and `X-Robots-Tag: noindex, nofollow`.
  4. Admin bundles are not loaded on public or traveler routes (verified by bundle analysis).

### P-1.1 Log in

* **Purpose:** Sign in through the IdP with Google, Apple or email (AUTH-001…003).
* **Interactions:** choose a provider → `GET /api/auth/login?intent=login&provider=…&next=`; link to Register and Forgot password; display a mapped error from `?error=`.
* **Components:** Button (provider buttons with official marks), Card, Alert (ErrorState inline), LocaleSwitcher.
* **API:** BFF `/api/auth/login` → IdP → `/api/auth/callback` → `POST /v1/auth/login {id_token, client: "web"}`.
* **Loading:** the provider button shows `L` until navigation.
* **Error:** `?error=access_denied | state_mismatch | idp_unavailable | account_suspended | age_restricted` → localized messages (02 §3.2). `account_suspended` includes the appeal path. Unknown codes show a generic message. Messages are uniform and never reveal whether an account exists (T-AUTH-04).
* **Empty:** n/a.
* **Authorization:** Guest; signed-in users → `next` or `/feed` (02 §3.1 rule 7).
* **Acceptance criteria:**
  1. Given a valid IdP login, the user lands on the validated `next` path (02 §3.3), or `/feed`, with a new `tb_session` (HttpOnly, Secure, SameSite=Lax) and a rotated `tb_csrf`.
  2. A `next` value of `//evil.example`, `https://evil.example` or `/api/x` is replaced by `/feed`.
  3. No password field is rendered by the web app (AUTH-001).
  4. Given a first-time IdP identity on Log in, the user is routed to the registration steps (age and consent) rather than silently registered.

### P-1.2 Register

* **Purpose:** Create an account: provider choice, then platform-specific requirements (AUTH-008, AUTH-009).
* **Interactions:** choose a provider (`intent=signup`); after the IdP returns, complete the **date of birth** (used transiently; only `birth_year` is stored server-side) and accept the **terms** and **privacy** versions; submit; the server routes to `/onboarding`.
* **Components:** Button, FormField, DatePicker (typed input alternative), Checkbox, links to `/legal/terms` and `/legal/privacy` (open in a new tab with a label), ErrorState.
* **API:** `/api/auth/login?intent=signup` → callback → `POST /v1/auth/register {id_token, client: "web", birth_date, accepted_terms_version, accepted_privacy_version, locale}`.
* **Loading:** submit button `L`.
* **Error:** `age_restricted` → "You must be 18 or older to use Travel Buddy." No account is created and no retry with another date is offered in the same session (AUTH-008). `validation_failed` → field errors. `conflict` (identity already registered) → sign the user in instead.
* **Empty:** n/a.
* **Authorization:** Guest.
* **Acceptance criteria:**
  1. Given a birth date making the user 17, the API answers `age_restricted`, no session cookie is set, and the localized refusal is shown (AUTH-008).
  2. Submit is disabled until both terms and privacy are explicitly checked; the checkboxes are never pre-checked (AUTH-009).
  3. The submitted payload contains the document versions displayed on screen.
  4. On success the user is redirected to `/onboarding` with a new session (PROF-002 path).
  5. The birth date is not persisted in browser storage or analytics.

### P-1.3 Forgot password

* **Purpose:** Hand off to the IdP password-reset flow (AUTH-005).
* **Interactions:** "Reset password" → the IdP's hosted reset page (via the IdP adapter); return link to Log in.
* **Components:** Card, Button, explanatory text.
* **API:** BFF → IdP reset URL (see §Open questions Q2). Platform sessions are revoked on password change by the backend (AUTH-005).
* **Loading / Error:** button `L`; `idp_unavailable` → ErrorState with Retry.
* **Empty:** n/a.
* **Authorization:** Guest. `noindex,nofollow`.
* **Acceptance criteria:**
  1. The page never asks for or transmits a password.
  2. The confirmation copy is identical whether or not the email exists (T-AUTH-04).
  3. The flow is reachable from Log in in one click (AUTH-005).

### P-1.4 Verify email

* **Purpose:** Show verification status and allow a resend. Unverified users can browse but cannot publish, message or send connection requests (AUTH-004).
* **Interactions:** "Resend verification email"; "I've verified", which re-checks status; continue to the app.
* **Components:** Card, Button, Alert, Spinner.
* **API:** `GET /v1/users/me` (`email_verified`); resend via the IdP adapter (Q2).
* **Loading:** status check skeleton.
* **Error:** `rate_limited` on resend → countdown.
* **Empty:** n/a.
* **Authorization:** Guest or Session.
* **Acceptance criteria:**
  1. Given a verified user, the page shows success and a "Continue" button to `/feed`.
  2. Resend is rate-limited client-side (60 s countdown) and server-side.
  3. Elsewhere in the app, any `403 email_unverified` banner links to this page.

### P-1.5 /dev/login

* **Purpose:** Development and test sign-in with seeded personas (ADR-0011).
* **Interactions:** pick a persona (free traveler, premium traveler, group owner, moderator, admin) or create a new dev identity (name and email) → `POST /api/auth/dev`.
* **Components:** Card, RadioGroup, Input, Button, Badge `mock`, EnvironmentBanner.
* **API:** `POST /v1/dev/idp/token {sub, email, name}` → dev ID token → `POST /v1/auth/login` (or `register` with `birth_date` and consent for a new identity).
* **Loading / Error:** button `L`; errors shown inline.
* **Empty:** n/a.
* **Authorization:** Guest; **404** unless `DevIdentityProvider` is active (`APP_ENV ∈ {development, test}`).
* **Acceptance criteria:**
  1. With `APP_ENV=production`, the server refuses to start if the dev identity provider is configured (T-AUTH-08), and `/dev/login` and `POST /api/auth/dev` return 404.
  2. Dev tokens go through the same `POST /v1/auth/login` path as production, and the resulting session is indistinguishable to the app.
  3. The page shows a permanent "Development identity — not for production" notice.

---

## Phase 2 — Public website

### P-2.1 Homepage

* **Purpose:** Convert visitors. Show destinations, stories and features, drive search, sign-ups and app downloads (brief §6).
* **Interactions:** hero destination search; CTAs "Start exploring" (→ `/destinations`), "Plan my trip" (→ `/register?intent=plan`; signed-in → `/assistant`), "Join the community" (→ `/register`); browse popular destinations; open featured stories; view the AI planner demo; read the companions, groups and audio-guide sections; view premium benefits; app store links.
* **Sections (in order):** 1 Hero ("Explore the World. Find Your People.") · 2 Destination search · 3 Discovery intro · 4 Popular destinations · 5 Featured stories · 6 AI itinerary demo (`#ai-planner`) · 7 Find companions (`#companions`) · 8 Group community · 9 Audio guides · 10 Premium benefits · 11 App Store / Google Play · 12 Footer.
* **Components:** DestinationHero-style hero with DestinationPlaceholder fallback, DestinationAutocomplete (inline), DestinationCard (`feature`, `default`), StoryCard, ItineraryPreview (static example), TravelerCard (illustrative, no real users), GroupCard (illustrative), PricingTable (summary variant), Button, Badge.
* **API:** `GET /v1/destinations?featured=true&limit=8`; `GET /v1/public/posts?featured=true&limit=6` *(featured filter ind.)*; `GET /v1/destinations/search?q=` (client, autocomplete); `GET /v1/billing/products?platform=web` (benefits and price "from").
* **Loading:** none at first render (ISR). Autocomplete shows `L` in its list.
* **Error:** when a section's data fails at build or revalidation, that section is omitted (the last good ISR version is served). The page never renders broken cards.
* **Empty:** no featured stories → the section is hidden; no featured destinations → curated launch set (DEST-005) from the catalog.
* **Authorization:** Public; signed-in → `/feed` (proxy).
* **Acceptance criteria:**
  1. The AI demo is labelled "Example itinerary". It is static content, makes no live generation call, and shows no opening hours or prices (AI-004).
  2. Companion and group illustrations use fictional sample data that is clearly illustrative. No real user's profile appears on the homepage.
  3. Choosing a destination in the hero search navigates to its destination page.
  4. App store badges link to the official store listings, which are configured per environment.
  5. Largest Contentful Paint ≤ 2.0 s (p75 mobile) with placeholder art, and CLS ≤ 0.05.
  6. JSON-LD `Organization` and `WebSite` (with `SearchAction`) are present (07).

### P-2.2 Destinations directory

* **Purpose:** Browse and search all destinations by region, country and category (LOC-006, DEST-001).
* **Interactions:** search by name (accent- and typo-tolerant); filter by region, country and travel category (ToggleChips); clear filters; open a destination; filters are reflected in the URL.
* **Components:** DestinationAutocomplete (field), ToggleChip, Select, DestinationCard grid, LoadMore, EmptyState, Sheet (mobile filters).
* **API:** `GET /v1/destinations?kind=city&region=&country=&category=&cursor=`; `GET /v1/destinations?kind=country` (filter options); `GET /v1/destinations/search?q=`.
* **Loading:** the unfiltered first page is ISR; filtered results show a skeleton grid client-side.
* **Error:** ErrorState inline above the grid with Retry; filters stay usable.
* **Empty:** "No destinations match these filters." + "Clear filters".
* **Authorization:** Public.
* **Acceptance criteria:**
  1. Searching "rio de janero" lists Rio de Janeiro among the first three results (DEST-001).
  2. Destination names render in the active locale ("Lisboa" in pt-BR and es, "Lisbon" in en) (DEST-002).
  3. Any query string makes the page `noindex,follow`, with the canonical pointing to `/destinations`.
  4. Filters work without JavaScript as plain GET links or forms (progressive enhancement); with JavaScript they update results without a full reload.

### P-2.3 Country page

* **Purpose:** Country overview with its cities and regions.
* **Interactions:** browse cities; jump to a region; open stories from the country; "Plan a trip to {country}".
* **Components:** DestinationHero, DestinationCard grid, StoryCard rail, Button.
* **API:** `GET /v1/destinations/lookup?path={country}`; `GET /v1/destinations?parent_id={id}&kind=city`; `GET /v1/public/posts?destination_id={id}&limit=6`.
* **Loading:** n/a (ISR).
* **Error:** lookup `404` → `notFound()`; a retired slug answers `redirect_to` → 308 (02 Q4).
* **Empty:** no cities yet → "We're still mapping {country}" + link to the directory; the page is `noindex` below the content threshold.
* **Authorization:** Public.
* **Acceptance criteria:**
  1. `/destinations/brazil` lists Brazilian cities from the catalog in popularity order.
  2. The breadcrumb and JSON-LD `BreadcrumbList` are present.
  3. `hreflang` alternates for all five locales plus `x-default` are present.

### P-2.4 Destination page

* **Purpose:** The SEO and inspiration page for a city (brief §6): overview, map, attractions, recommendations, stories, itineraries, audio guides, FAQ, planning CTA.
* **Interactions:** read the overview; view the location map; browse attractions by category; open public stories; open suggested itineraries; open audio guides; expand FAQ items; "Plan my trip" / "Generate an itinerary" (gate→login, then `/assistant?destination=`); Save destination (client island, gate→login); share the page.
* **Components:** DestinationHero (photo credit or DestinationPlaceholder), MapView (`static`, lazy), PlaceMarker, Card lists by category, StoryCard rail, TripCard (suggested itineraries; from Phase 6), GuideCard *(Phase 6)*, Accordion (FAQ), SaveButton, Button.
* **API:** `GET /v1/destinations/lookup?path={country}/{city}`; `GET /v1/destinations/{id}/places?category=&limit=` (DEST-003, Phase 6 data; Phase 2 shows curated highlights from the destination record); `GET /v1/public/posts?destination_id={id}&limit=6`; `GET /v1/guides?destination_id={id}` (Phase 6); save → `PUT /v1/users/me/saved-places/{id}` *(ind.)* through the BFF.
* **Loading:** the map lazy-loads with a static placeholder of identical size.
* **Error:** map style failure → "Map unavailable" card with an OpenStreetMap link to the city centre; other sections are independent.
* **Empty:** no stories → "No stories from {city} yet. Share yours" (gate→login → composer prefilled with the destination); no guides → section hidden.
* **Authorization:** Public. Personal state (saved) comes only from the client island.
* **Acceptance criteria:**
  1. No live facts (opening hours, prices, entry rules, safety status) appear unless sourced from licensed data carrying `data_freshness_at`, which is displayed (AI-004, DEST-003, brief §6).
  2. Long-form copy without a translation renders with `lang="en"` and a visible "Shown in English" note (01 §12).
  3. Every place shows source attribution when it comes from licensed data (DEST-003).
  4. Only `PublicPost` items appear in the stories rail (public + approved).
  5. The map is supplementary: every marker on it is also in the attraction list.
  6. JSON-LD `TouristDestination` + `BreadcrumbList` + `FAQPage` (when FAQs exist) validate (07).

### P-2.5 Public stories index

* **Purpose:** Browse publicly shared travel stories (SEO, inspiration).
* **Interactions:** filter by destination (DestinationAutocomplete); load more; open a story.
* **Components:** StoryCard grid, DestinationAutocomplete, LoadMore, EmptyState.
* **API:** `GET /v1/public/posts?destination_id=&cursor=&limit=20`.
* **Loading:** page 1 ISR (600 s); later pages via client skeletons.
* **Error:** inline ErrorState with Retry.
* **Empty:** "No public stories here yet." + "Explore destinations".
* **Authorization:** Public. Anonymous paging follows the guest cap (AUTH-012). After 20 items, "Join to see more" (gate→login) replaces LoadMore (02 Q8).
* **Acceptance criteria:**
  1. Only posts with `visibility=public` and moderation `approved` appear (public endpoint contract).
  2. `?cursor=` and `?destination=` variants are `noindex,follow`, with the canonical pointing to `/stories`.
  3. After a story is deleted or made non-public, it disappears from page 1 within the revalidation window (≤ 10 min), or immediately once on-demand revalidation exists (02 Q1).

### P-2.6 Public story

* **Purpose:** An indexable page for a post whose author explicitly chose **Public** visibility (brief §6).
* **Interactions:** read; view media; open the author's public profile (if public); open the tagged destination; share; report (gate→login → ReportDialog); "Join to react and comment".
* **Components:** PostCard (`detail`, read-only actions), Avatar, Badge (destination tags), ReactionBar (gate→login), ReportDialog, StoryCard rail (related), DestinationCard.
* **API:** `GET /v1/public/posts/{id}`; related: `GET /v1/public/posts?destination_id=&limit=4`.
* **Loading:** n/a (ISR, 600 s plus on-demand purge per 02 Q1).
* **Error:** API `404` (non-public, deleted, removed, author suspended) → HTTP **404**, `noindex`. Identical for every reason.
* **Empty:** n/a.
* **Authorization:** Public.
* **Acceptance criteria:**
  1. Given a post with `visibility ≠ public` or moderation ≠ `approved`, the URL returns 404 and never appeared in a sitemap.
  2. The author attribution shows display name, handle and avatar only. No email or location beyond the post's chosen precision (POST-002, PROF-005).
  3. Precise GPS coordinates are never rendered. Place tags reference public places only (T-LOC-06).
  4. The post body has `lang` set to the post's language. The canonical follows 02 §2.6 (locale matching the post language).
  5. JSON-LD `Article` (or `SocialMediaPosting`) carries `author`, `datePublished`, `dateModified` and `contentLocation` (destination name only).
  6. Report is reachable in one click and, for anonymous users, returns to the story after login.

### P-2.7 Pricing

* **Purpose:** Present premium benefits and plans. From Phase 5, start checkout (BILL-001, ADR-0012).
* **Interactions:** toggle monthly/annual; compare Free vs Premium; "Get Premium" → `/membership/checkout?product=` (gate→login); FAQ.
* **Components:** PricingTable, ToggleChip (period), Accordion (FAQ), EntitlementGate (current plan island), Button.
* **API:** `GET /v1/billing/products?platform=web` (ISR); `GET /v1/billing/entitlements` (client island, signed-in only).
* **Loading:** the current-plan island shows a neutral placeholder.
* **Error:** products unavailable at revalidation → the last good version is served. Never hard-coded prices.
* **Empty:** n/a.
* **Authorization:** Public. Signed-in users who already hold `premium` through a store subscription see "You're Premium via App Store / Google Play" and **no** web purchase button (ADR-0012, 07 §2).
* **Acceptance criteria:**
  1. Prices are formatted from Stripe Price data per locale and currency, and none are hard-coded in the web code (07 §2).
  2. Until the Stripe adapter exists, or in mock mode, the buy button is disabled with "Checkout isn't available yet on web". No simulated purchase is possible (01 §7.1).
  3. Benefits listed match the 07 §3 feature and quota table (for example AI generations 5 vs 60 per month, offline packs 1 vs 15). Numbers come from configuration or API, not copy.
  4. JSON-LD `Product`/`Offer` is emitted only when real prices are available.

### P-2.8 Download

* **Purpose:** Direct users to the iOS and Android apps.
* **Interactions:** store badges; QR code on desktop (to the store listing); "Continue on web" → `/register`.
* **Components:** Card, official store badges, QR image (generated at build), Button.
* **API:** none.
* **Loading / Error / Empty:** n/a.
* **Authorization:** Public.
* **Acceptance criteria:**
  1. Badges use the official artwork and link to the configured listing URLs.
  2. The QR code encodes the same URL as the badge and has a text alternative.

### P-2.9 About

* **Purpose:** Explain the platform, its values (privacy by default, honest AI) and how safety works.
* **Interactions:** read; links to the community guidelines and privacy policy.
* **Components:** Container (prose), Card.
* **API:** none.
* **Loading / Error / Empty:** n/a.
* **Authorization:** Public.
* **Acceptance criteria:**
  1. Copy never describes meeting strangers as "safe" or travelers as "verified" (DISC-010).
  2. It states plainly that messages are not end-to-end encrypted in v1 (DM-013).

### P-2.10 Legal pages

Routes: `/legal/terms`, `/legal/privacy`, `/legal/cookies`, `/legal/community-guidelines`.

* **Purpose:** Versioned legal documents referenced by registration consent (AUTH-009) and moderation reasons.
* **Interactions:** read; table of contents; print; the version and effective date are visible.
* **Components:** Container (prose), table of contents (in-page nav), Badge (version).
* **API:** none. Static content per locale, with the version identifier shared with `POST /v1/auth/register`.
* **Loading / Error / Empty:** n/a. A locale without a translation shows the English text with `lang="en"` and a note.
* **Authorization:** Public.
* **Acceptance criteria:**
  1. Each page shows a version ID that equals the version sent at registration.
  2. The privacy policy states the v1 messaging encryption status (DM-013), the retention summary (SAFE-009) and the lawful bases (doc 08 §5.1).
  3. The community-guidelines headings match the moderation reason taxonomy used by ModerationActionDialog.

---

## Phase 3 — Social experience

### P-3.1 Onboarding

* **Purpose:** Seven skippable steps after registration, then the personalized feed (brief §8, PROF-001/002).
* **Steps:** 1 **Profile basics**: display name (required), handle (PROF-003), photo (optional), bio (optional) · 2 **Language** (required, defaults to the UI locale) · 3 **Interests and travel styles** · 4 **Home country** (optional) · 5 **Current or upcoming destination** · 6 **Location permission**: explanation only; the browser prompt is triggered only by an explicit "Allow location" click; "Not now" is the default path · 7 **Nearby traveler discovery**: **off by default**; enabling opens the consent screen with SafetyGuidance (DISC-001, DISC-010).
* **Interactions:** Next, Back, Skip (steps 3–7); upload photo; choose interests (ToggleChips); pick a destination; finish → `/feed`.
* **Components:** OnboardingStepper, FormField, Input, Textarea, MediaUploader (avatar), Select, ToggleChip, DestinationAutocomplete, Switch, SafetyGuidance, Dialog (discovery consent), Progress.
* **API:** `PATCH /v1/users/me`; `PATCH /v1/users/me/preferences` (language, interests, travel styles); `PUT /v1/users/me/browse-destination`; `PATCH /v1/users/me/privacy` (`discovery_enabled` only with recorded consent); `POST /v1/media/uploads` + `/finalize` (avatar); `POST /v1/users/me/onboarding/complete`.
* **Loading:** step transitions are instant (local state); saving shows the button `L`.
* **Error:** handle taken → field error with suggestions; save failure → inline ErrorState, and the step's values are kept.
* **Empty:** n/a.
* **Authorization:** Session; already onboarded → `/feed` (02 §3.1 rule 13).
* **Acceptance criteria:**
  1. Only display name and language are required. Every other step can be skipped, and Skip saves nothing for that step (PROF-001).
  2. The browser geolocation prompt never appears unless the user clicks "Allow location" on step 6.
  3. Given the user finishes without touching step 7, `discovery_enabled` stays `false` (DISC-001).
  4. Enabling discovery requires the consent dialog with safety guidance, and the API receives an explicit consent flag (DISC-001, DISC-010).
  5. **E2E (PROF-002, FEED-001):** registration → onboarding (all optional steps skipped) → `/feed` shows ≥ 1 post.
  6. Locations are never inferred from IP, and nationality or home country are never used to pick feed content (LOC-004, POST-003).

### P-3.2 Home feed

* **Purpose:** The location-relevant social feed (brief §10, FEED-001…007).
* **Interactions:** switch tabs **For You / Nearby / Following / Destinations** (`?tab=`); change location context (selected destination, country, city, neighborhood; "Use my location"; radius 1/5/25/50 km for Nearby); sort recent/popular; filter categories and content language; infinite scroll; react (one reaction, changeable); comment (→ post detail); bookmark; share (public posts only); report; hide / not interested / see less from author (FEED-007); create post.
* **Components:** FeedTabs, LocationFilterBar, DestinationAutocomplete, PostCard, ReactionBar, ReportDialog, InfiniteSentinel + LoadMore, Skeleton, EmptyState, OnlineOnlyBadge, Toast, FAB (mobile).
* **API:** `GET /v1/feed?tab=for_you|nearby|following|destinations&destination_id=&near=&near_ts=&near_accuracy_m=&radius_km=&sort=&category=&language=&cursor=&limit=20`, which returns `{data, page:{next_cursor, has_more, reset?}, context:{source, destination}}`; `GET /v1/destinations/resolve?near=` (when "Use my location"); `PUT /v1/users/me/browse-destination`; `POST /v1/posts/{id}/reactions {reaction}` / `DELETE /v1/posts/{id}/reactions/me`; `PUT/DELETE /v1/posts/{id}/bookmark`; `POST /v1/posts/{id}/feedback` *(ind.)*; `POST /v1/reports`.
* **Loading:** server prefetch of page 1 with `HydrationBoundary`; five PostCard skeletons on tab change.
* **Error:** feed failure → ErrorState with Retry, keeping tabs and filters. `stale_location` → silently re-acquire location once, then fall back to the selected destination with a notice (LOC-007). Geolocation denied → fall back to the selected destination with "Location is off. Showing {destination}". Mock mode, Nearby → "Live location isn't available in this environment", with the selected destination used instead.
* **Empty:** For You is never empty (FEED-001 fallback chain, so empty is a defect). Following with no follows → "Follow travelers to see their posts here" + suggested authors. Destinations with no chosen destinations → "Choose destinations to follow" + DestinationAutocomplete. Nearby with no posts in the radius → "Nothing nearby yet" + widen-radius action.
* **Authorization:** Onboarded. Blocked users' content is excluded server-side in both directions (FEED-005).
* **Acceptance criteria:**
  1. Given a UK traveler with location permission in Rio de Janeiro, Nearby and For You prioritize posts tagged Rio de Janeiro, and the header reads "Showing Rio de Janeiro · based on your location" (`context.source = gps`).
  2. Given the same traveler selects Tokyo, the feed reloads with Tokyo content, and `context.source = selected` is reflected in the header.
  3. The web sends `near` rounded to 3 decimals together with `near_ts` and `near_accuracy_m`. Coordinates never appear in the page URL, logs, analytics or local storage (LOC-003, doc 08 T-LOC-07).
  4. Nationality, home country and IP are never sent as relevance inputs (LOC-004, POST-003).
  5. Reacting updates instantly. On API failure the UI rolls back and a toast offers Retry. Changing the reaction replaces it (one per user) (POST-005).
  6. Across 10 consecutive pages there are no duplicates. When `page.reset=true`, the client restarts and shows "Feed refreshed" (FEED-004).
  7. Hiding a post removes it immediately, and it never reappears (FEED-007).
  8. Infinite scroll has a keyboard-reachable "Load more", and new items are announced politely.

### P-3.3 Post composer

* **Purpose:** Create a travel post: text, photos, short video, destination tags, attractions, categories (brief §11, POST-001/002/004/008/009).
* **Interactions:** choose a kind (text, photo, video, story, recommendation, review with 1–5 rating, tip, itinerary summary, experience); write a caption; add media (drag-and-drop or picker, with progress); add alt text; tag a destination and optional public place; choose location precision (**none / destination / public place**); choose visibility (**public / followers / connections / private**); add up to 10 tags and categories; save draft automatically; publish.
* **Components:** PostComposer, MediaUploader, DestinationAutocomplete, Combobox (place), RadioGroup (precision, visibility), ToggleChip (categories), Textarea, Progress, Dialog / Sheet, Toast.
* **API:** `POST /v1/media/uploads` → presigned PUT → `POST /v1/media/{id}/finalize`; `GET /v1/media/{id}` (status polling); `POST /v1/posts` with `Idempotency-Key`; `GET /v1/destinations/search`; `GET /v1/destinations/{id}/places?q=`.
* **Loading:** per-file upload progress; the publish button stays `L` until the server confirms.
* **Error:** `unsupported_media_type`, `payload_too_large` → per-file error with remove. `email_unverified` → banner (AUTH-004). Account `restricted` → composer disabled with the reason and end date (03 §6). Publish failure → the draft is kept and Retry reuses the same `Idempotency-Key`.
* **Empty:** n/a.
* **Authorization:** Onboarded, `active` account, verified email.
* **Acceptance criteria:**
  1. Precise GPS coordinates are never sent or published. The "public place" option offers only catalog places (T-LOC-06).
  2. The served media variants contain no EXIF/GPS metadata. This is a server responsibility, and the web shows "Processing…" until the asset is `ready` (POST-004).
  3. The visibility default comes from the user's privacy setting (PROF-007). **Public** is never preselected silently for a new account, and choosing it shows "Anyone, including people without an account and search engines, can see this post." Private accounts cannot choose Public (PROF-004).
  4. Drafts survive a page reload: text and settings go to `localStorage`, media references are kept while uploads are pending, and the draft is cleared on publish.
  5. A review cannot be published without a 1–5 rating (POST-001). Images cannot be published without alt text.
  6. Retrying a publish after a network failure creates exactly one post (idempotency).
  7. Drag-and-drop works on desktop, with an equivalent "Choose files" button.

### P-3.4 Post detail

* **Purpose:** A single post with comments (one reply level) in the app.
* **Interactions:** react; bookmark; share (public only); comment and reply; delete own comment, or comments on own post; report the post or a comment; follow the author; edit or delete own post (menu).
* **Components:** PostCard (`detail`), ReactionBar, comment list (Avatar, Textarea, DropdownMenu), ReportDialog, Dialog (delete confirm), LoadMore.
* **API:** `GET /v1/posts/{id}`; `GET/POST /v1/posts/{id}/comments`; `DELETE /v1/comments/{id}` *(ind.)*; reactions and bookmark as P-3.2; `PUT/DELETE /v1/users/{id}/follow`; `DELETE /v1/posts/{id}`; `POST /v1/reports`.
* **Loading:** post skeleton, then comments skeleton.
* **Error:** `404` → not found (covers non-visible posts, POST-008). Comment `blocked_relationship` → "Not available".
* **Empty:** no comments → "Be the first to comment". Comments off → "Comments are turned off".
* **Authorization:** Onboarded; visibility enforced by the API (404 when not visible).
* **Acceptance criteria:**
  1. Given a followers-only post and a viewer who is not a follower, the page returns 404 (POST-008).
  2. Replies are limited to one level, and reply-to-reply attaches to the top comment (POST-005).
  3. Deleting own post asks for confirmation, then redirects to `/feed`. The post disappears from feeds within 60 s (POST-007, server).
  4. Edited posts show "Edited" (POST-007).

### P-3.5 Edit post

* **Purpose:** Edit caption, tags, destination, precision and visibility of an own post.
* **Interactions:** as the composer; media can be removed (adding media follows the same pipeline); save; cancel.
* **Components:** PostComposer (`page`, edit mode).
* **API:** `GET /v1/posts/{id}`; `PATCH /v1/posts/{id}`.
* **Loading:** composer skeleton.
* **Error:** not the author → 404. Conflict → reload prompt.
* **Empty:** n/a.
* **Authorization:** Author only (03 §5.1).
* **Acceptance criteria:**
  1. A non-author gets 404 for `/posts/{id}/edit`.
  2. After save, the post shows "Edited" and the new visibility takes effect immediately in direct GET (POST-007/008).
  3. Changing visibility from public to anything else removes the public story page, as in P-2.6 criterion 1 (02 Q1 for latency).

### P-3.6 Saved

* **Purpose:** Bookmarked posts (Phase 3), plus saved places and tours (Phase 6) (TRIP-003).
* **Interactions:** switch tabs Posts / Places / Tours; open an item; unsave.
* **Components:** Tabs, PostCard (`compact`), Card (place), TourCard *(ind.)*, LoadMore, EmptyState.
* **API:** `GET /v1/users/me/bookmarks` *(ind.)*; `GET /v1/users/me/saved-places`; saved tours *(ind.)*; unsave via the matching `DELETE`.
* **Loading:** list skeleton.
* **Error:** inline ErrorState.
* **Empty:** per tab: "Save posts with the bookmark icon", "Save places from destination pages".
* **Authorization:** Onboarded; own data only.
* **Acceptance criteria:**
  1. Unsaving removes the item optimistically and restores it with a toast on failure.
  2. Saved posts that became invisible to the viewer are omitted.

### P-3.7 Own profile

* **Purpose:** The traveler's own profile: posts, trips, saved destinations, connections, groups, badges (brief §23).
* **Interactions:** switch tabs Posts / Trips / Saved / Groups; edit profile; open connections and badges; share profile link (if public); view as others ("Preview public profile").
* **Components:** profile header (Avatar, Badge `premium`), Tabs, PostCard, TripCard, GroupCard, Button, EmptyState.
* **API:** `GET /v1/users/me`; `GET /v1/users/{userId}/posts` *(ind.)*; `GET /v1/trips?scope=mine` (Phase 6); `GET /v1/groups?scope=mine` (Phase 5).
* **Loading:** header and tab skeletons.
* **Error:** per-tab ErrorState.
* **Empty:** no posts → "Share your first travel moment" + Create post.
* **Authorization:** Onboarded (own profile).
* **Acceptance criteria:**
  1. "Preview public profile" renders exactly the `PublicProfile` projection (PROF-005).
  2. Trips are hidden from the public projection unless `show_trips_on_profile=true`, which defaults to false (doc 08 T-LOC-08).

### P-3.8 Edit profile

* **Purpose:** Edit display name, handle, photo, bio, home country, interests, languages.
* **Interactions:** edit fields; upload or remove photo; save; cancel.
* **Components:** FormField, Input, Textarea, MediaUploader, Select, ToggleChip.
* **API:** `GET/PATCH /v1/users/me`; media upload endpoints.
* **Loading:** form skeleton; save `L`.
* **Error:** handle change within 30 days → field error with the next allowed date (PROF-003). Validation errors are mapped to fields.
* **Empty:** n/a.
* **Authorization:** Onboarded (own).
* **Acceptance criteria:**
  1. Handle uniqueness is case-insensitive, and the error suggests alternatives (PROF-003).
  2. Home location is limited to country and optional free-text region, never coordinates (LOC-001).

### P-3.9 Public profile

* **Purpose:** Another traveler's profile, public and shareable.
* **Interactions:** view the public posts grid; follow (gate→login); connect (Phase 4, client island); block and report (menu, client island).
* **Components:** profile header, PostCard grid, ConnectionButton (island), DropdownMenu, ReportDialog.
* **API:** server: `GET /v1/users/{userId}` (anonymous projection) + `GET /v1/public/posts?author=` *(ind.)*. Client island: `GET /v1/users/{userId}` through the BFF (relationship, connection-only fields), `PUT/DELETE /v1/users/{id}/follow`, `PUT /v1/users/{id}/block`, `POST /v1/reports`.
* **Loading:** the island shows a placeholder action bar.
* **Error:** API 404 (non-existent, not public, blocked either way) → HTTP 404, `noindex`, identical for all cases.
* **Empty:** no public posts → "No public posts yet".
* **Authorization:** Public, but visible only when `profile_visibility=public`. Indexable only with search-engine consent. The signed-in view is per 02 Q2.
* **Acceptance criteria:**
  1. The page contains none of email, birth data, sessions, coordinates or exact location (PROF-005, contract test).
  2. Given that A blocked B, B (signed in) sees the 404 page for A's handle.
  3. Without explicit search-engine consent, the page sends `noindex` and is absent from sitemaps.
  4. A private account's posts are not listed for non-followers (PROF-004).

### P-3.10 Account settings

* **Purpose:** Account hub: email (IdP-managed), language, units, time zone, currency, theme, sign-in providers, log out.
* **Interactions:** change preferences (PROF-006); open the sub-pages Privacy, Notifications, Sessions, Data, Membership.
* **Components:** Card list, Select, RadioGroup, ThemeToggle (inline), LocaleSwitcher (menu), Button.
* **API:** `GET/PATCH /v1/users/me/preferences`; `GET /v1/users/me`.
* **Loading:** form skeleton.
* **Error:** inline save errors per field.
* **Empty:** n/a.
* **Authorization:** Session (reachable before onboarding completes).
* **Acceptance criteria:**
  1. Changing the UI language re-renders in the new locale without a full sign-out (PROF-006) and redirects to the matching locale prefix.
  2. Email is shown to its owner only and changed through the IdP.

### P-3.11 Privacy settings

* **Purpose:** The privacy centre (PROF-007): profile visibility, account private/public, search-engine indexing, discovery (Phase 4), connection-request policy, read receipts, default post visibility, default location precision, blocked users.
* **Interactions:** toggle and choose settings (each saves immediately with a toast); manage the blocked list (unblock); enable discovery (consent flow); invisible mode.
* **Components:** Switch, RadioGroup, Select, Dialog (consent), SafetyGuidance, list with Button (unblock).
* **API:** `GET/PATCH /v1/users/me/privacy`; `GET /v1/users/me/blocks`; `DELETE /v1/users/{id}/block`.
* **Loading:** skeleton rows; Switch `L` while saving.
* **Error:** the save failure reverts the control and shows a toast.
* **Empty:** no blocked users → "You haven't blocked anyone".
* **Authorization:** Session (own). Never paywalled (03 §5.8).
* **Acceptance criteria:**
  1. Every setting persists server-side and applies immediately (PROF-007).
  2. Discovery is off by default and turning it on requires the consent dialog (DISC-001). Turning it off is one click and takes effect instantly.
  3. `connection_requests_from` offers everyone / shared context / nobody (CONN-004).
  4. Read receipts are reciprocal: turning them off shows "You also won't see others' read status" (DM-007).

### P-3.12 Sessions

* **Purpose:** List and revoke signed-in devices (AUTH-006).
* **Interactions:** view sessions (client type, browser and OS, approximate last activity, current marker); revoke one; revoke all others.
* **Components:** Card list, Badge (current), Button (danger), AlertDialog.
* **API:** `GET /v1/users/me/sessions`; `DELETE /v1/users/me/sessions/{id}`.
* **Loading:** row skeletons.
* **Error:** inline ErrorState.
* **Empty:** n/a (the current session always exists).
* **Authorization:** Session (own).
* **Acceptance criteria:**
  1. Web sessions are labelled from `client: "web"` ("Web · Chrome on macOS") (ADR-0011).
  2. Revoking the current session signs the user out. Revoking another ends that device's refresh capability and WebSocket within 60 s (AUTH-006, server).
  3. Sessions show no IP-derived location.

---

## Phase 4 — Companions and messaging

### P-4.1 Companion discovery

* **Purpose:** Opt-in discovery of compatible travelers in a chosen destination (brief §15, DISC-001…011).
* **Interactions:** if not opted in: read the explanation and safety guidance, then start a discovery session (choose destination and optional neighborhood, duration 24 h default, max 72 h). If opted in: filter by interests, travel dates, languages and travel styles; view TravelerCards; connect; open a profile preview; block or report; go invisible; end the session; switch destination (rate-limited).
* **Components:** DiscoveryStatusIndicator, SafetyGuidance, Dialog (consent), DestinationAutocomplete, DateRangePicker, ToggleChip, TravelerCard, ConnectionButton, ReportDialog, LoadMore, EmptyState.
* **API:** `GET/POST/DELETE /v1/discovery/session` (POST carries `destination_id`, optional `area_destination_id`, `duration_hours` and consent); `GET /v1/discovery/travelers?destination_id=&interests=&from=&to=&languages=&styles=&cursor=`; `POST /v1/connection-requests`; `PUT /v1/users/{id}/block`; `POST /v1/reports`.
* **Loading:** card grid skeleton.
* **Error:** `discovery_invisible` (DISC-006) → "You're in invisible mode", with a toggle to become visible. `rate_limited` (60 queries/h, 10 destination switches/day, DISC-009) → message with the reset time. Mock mode is not affected, because discovery is not live location.
* **Empty:** opted in but no matches → "No travelers in {area} match right now. Try widening filters." It never suggests nearby people outside the destination.
* **Authorization:** Onboarded, plus an active discovery session to see others (03 §5.3). Blocked users never appear (DISC-008).
* **Acceptance criteria:**
  1. Cards show only the area label (city or neighborhood), never distance, coordinates or "last seen" (DISC-004, LOC-009, T-LOC-04).
  2. Date overlap is shown as "Dates overlap · N days" and never reveals the other user's full schedule (brief §15).
  3. A new account has discovery off. The page shows the opt-in explanation, and no results are fetched until a session starts (DISC-001).
  4. Safety guidance (doc 08 §7) is shown before the first enablement and in profile previews, and the page never calls discovery "safe" (DISC-010).
  5. The session expiry is visible at all times, and the session disappears after the TTL without user action (DISC-002, T-LOC-09).
  6. The full travel guide (trips, guides, AI) remains usable without ever enabling discovery (DISC-011, E2E).

### P-4.2 Connection requests

* **Purpose:** Incoming and outgoing connection requests (CONN-003).
* **Interactions:** switch Incoming / Outgoing; accept; decline; cancel; open a profile; block or report the requester.
* **Components:** Tabs, TravelerCard (`list`), ConnectionButton, ReportDialog, EmptyState, Toast.
* **API:** `GET /v1/connection-requests?direction=incoming|outgoing&cursor=`; `POST /v1/connection-requests/{id}/accept|decline|cancel`; block and report as above.
* **Loading:** list skeleton.
* **Error:** stale request (expired after 30 days, CONN-007; or withdrawn) → "This request is no longer available", and the row is removed.
* **Empty:** Incoming → "No pending requests". Outgoing → "You haven't sent any requests".
* **Authorization:** Onboarded (own requests).
* **Acceptance criteria:**
  1. Accepting creates the connection only on explicit action (CONN-002), and SafetyGuidance is shown on the first acceptance (SAFE-008).
  2. Outgoing declined requests show "Declined" (PRD Q-4 default), and re-requesting within 30 days is blocked with `connection_request_cooldown` (CONN-006). See Open questions Q3.
  3. Blocking from this page removes the request and hides the user everywhere (CONN-009).

### P-4.3 Connections

* **Purpose:** List the viewer's connections and manage them.
* **Interactions:** search; message (connected users only); remove connection (silent, CONN-008); block; report.
* **Components:** Input (search), TravelerCard (`list`), DropdownMenu, AlertDialog, EmptyState.
* **API:** `GET /v1/connections?q=&cursor=`; `DELETE /v1/connections/{user_id}`; `POST /v1/conversations/direct {user_id}`.
* **Loading:** list skeleton.
* **Error:** inline ErrorState.
* **Empty:** "No connections yet. Find travelers in Companions."
* **Authorization:** Onboarded (own).
* **Acceptance criteria:**
  1. Removing a connection does not notify the other user (CONN-008).
  2. After removal, opening a DM with that user is refused (`connection_required`, DM-001).

### P-4.4 Messages

* **Purpose:** The conversation list. On desktop, a persistent two-pane layout (brief §17).
* **Interactions:** search conversations; open one; see unread counts; muted and blocked indicators; start a new DM from connections.
* **Components:** ConversationList, Input (search), EmptyState, OnlineOnlyBadge, MessageThread pane (desktop).
* **API:** `GET /v1/conversations?cursor=&q=`; realtime ticket via `POST /api/realtime/ticket` (ADR-0013); WebSocket events update counts.
* **Loading:** list skeleton. A reconnecting banner appears when the socket is down for more than 3 s.
* **Error:** list failure → ErrorState. Realtime unavailable → "Reconnecting…" with REST polling every 30 s. Mock mode → "Live chat isn't available in this environment" (01 §7.1); history is still readable if mocked.
* **Empty:** "No conversations yet. Connect with travelers to start chatting."
* **Authorization:** Onboarded.
* **Acceptance criteria:**
  1. Unread counts update in real time and are announced in the list item's accessible name.
  2. Tickets never appear in URLs. A reconnect fetches a fresh ticket (ADR-0013).
  3. The desktop layout keeps the list visible while a thread is open; on mobile it is list-or-thread.

### P-4.5 Conversation

* **Purpose:** A one-to-one conversation between **connected** users (DM-001…013).
* **Interactions:** read history (paginate older); send text and photos; reply; react; edit within 15 min; delete for everyone; see delivery and read status (if both enabled); typing indicator; mute; block; report the conversation or a message; retry failed messages.
* **Components:** MessageThread, MessageComposer, TypingIndicator, MediaUploader, DropdownMenu, ReportDialog, AlertDialog.
* **API:** `GET /v1/conversations/{id}/messages?before_seq=|after_seq=`; `POST /v1/conversations/{id}/messages` (REST fallback, with `client_message_id`); WebSocket `message.send` / `message.ack` / `message.new` (doc 06 realtime); `PATCH/DELETE /v1/messages/{id}`; `PUT/DELETE /v1/messages/{id}/reactions/{emoji}`; `POST /v1/conversations/{id}/read {seq}`; `PUT/DELETE /v1/conversations/{id}/mute`; media upload (private purpose); `PUT /v1/users/{id}/block`; `POST /v1/reports`.
* **Loading:** history skeleton; older pages load at the top with scroll anchoring.
* **Error:** failed send → message marked "Not sent · Retry" (same `client_message_id`). Gap detected (seq jump) → automatic `after_seq` sync (DM-006). `connection_required` or blocked → composer replaced by "You can't send messages in this conversation".
* **Empty:** new conversation → "Say hello to {name}" + SafetyGuidance link.
* **Authorization:** Conversation member, else **404** (T-AZ-01).
* **Acceptance criteria:**
  1. A user who is not a member of conversation X gets 404 for `/messages/X`, and no message data is in the response.
  2. Sending the same message twice (retry) creates one message (DM-005).
  3. After a forced disconnect, messages sent meanwhile appear in order without duplicates after reconnect (DM-004, DM-006).
  4. Edits are only possible within 15 minutes and show "Edited". Delete leaves a tombstone (DM-010).
  5. With read receipts disabled, the user neither sends nor sees read state (DM-007).
  6. Attachments load through short-lived signed URLs, and image URLs are not reused across users (T-MSG-04).
  7. The UI never implies end-to-end encryption (DM-013).

### P-4.6 Notifications

* **Purpose:** In-app notification centre (NOTIF-001).
* **Interactions:** view notifications grouped by day; open the target; mark one or all as read; jump to settings.
* **Components:** NotificationList, NotificationItem, Button, EmptyState, LoadMore.
* **API:** `GET /v1/notifications?cursor=`; `POST /v1/notifications/read {ids | all}`.
* **Loading:** list skeleton.
* **Error:** inline ErrorState.
* **Empty:** "You're all caught up."
* **Authorization:** Onboarded (own).
* **Acceptance criteria:**
  1. Opening a notification marks it read and navigates to the target. A target that is no longer visible shows the not-found page.
  2. Notifications never include coordinates and never reveal blocked users' activity.

### P-4.7 Notification settings

* **Purpose:** The per-type notification matrix (in-app, email, web push), quiet hours, and browser notification permission (PROF-006, NOTIF-002/003).
* **Interactions:** toggle per type and channel; set quiet hours (time zone); enable browser notifications (explicit button → permission prompt → push subscription); disable.
* **Components:** table of Switches, Select (time zone), time inputs, Button, Alert (permission denied help).
* **API:** `GET/PATCH /v1/users/me/preferences` (notification matrix); `POST /v1/users/me/devices` (webpush variant) / `DELETE /v1/users/me/devices/{id}` (NOTIF-005).
* **Loading:** skeleton rows.
* **Error:** browser denied permission → explanation of how to re-enable in browser settings.
* **Empty:** n/a.
* **Authorization:** Session (own).
* **Acceptance criteria:**
  1. The browser permission prompt appears only after the user clicks "Enable browser notifications", never on page load (01 §8).
  2. Disabling message previews means push payloads contain no message body (NOTIF-004, server); the setting is shown here.
  3. Unsupported browsers show "Browser notifications aren't supported here" instead of a broken toggle.

---

## Phase 5 — Groups and monetization

### P-5.1 Membership

* **Purpose:** Membership dashboard: plan, status, renewal or end date, provider, quotas, management (brief §22).
* **Interactions:** view plan and status (07 §4: active, cancelled-ends-on, grace, billing retry, paused, expired); view quota meters; "Manage subscription" (Stripe portal for web purchases, or a store link); upgrade (→ `/pricing`); view purchase history where available.
* **Components:** Card, Badge, Progress (quota meters), EntitlementGate, Button, table (purchases).
* **API:** `GET /v1/billing/entitlements`; `GET /v1/users/me/subscriptions`; `GET /v1/users/me/purchases` *(ind.)*; `POST /v1/billing/portal-sessions`.
* **Loading:** card skeletons.
* **Error:** portal creation failure → ErrorState with Retry. Mock mode → "Billing isn't available in this environment".
* **Empty:** Free plan → benefits summary + "See Premium".
* **Authorization:** Onboarded (own).
* **Acceptance criteria:**
  1. A store-purchased subscription shows "Managed in App Store / Google Play" with a link, and no Stripe portal button (ADR-0012).
  2. `in_grace_period` shows "Update your payment method" (07 §4).
  3. Quota meters show `used / limit` and the `resets_at` date from the API (07 §7).
  4. No card numbers or payment details are ever displayed or requested.

### P-5.2 Checkout hand-off

* **Purpose:** Create a Stripe Checkout Session and redirect to it (ADR-0012).
* **Interactions:** automatic: show "Redirecting to secure checkout…", with a manual "Continue" link as fallback.
* **Components:** Card, Spinner, Button.
* **API:** `POST /v1/billing/checkout-sessions {product_id, success_path, cancel_path}` with `Idempotency-Key`.
* **Loading:** the redirect spinner.
* **Error:** `entitlement` already active → back to `/membership`. `503 feature_not_available_in_mock` or adapter missing → "Checkout isn't available yet on web". Other errors → ErrorState with Retry.
* **Empty:** n/a.
* **Authorization:** Onboarded.
* **Acceptance criteria:**
  1. The page never renders card fields. Payment happens only on Stripe's hosted page (SAQ-A).
  2. Double-clicking or refreshing creates at most one checkout session (idempotency).
  3. No payment is ever simulated in mock mode (01 §7.1).

### P-5.3 Payment confirmation

* **Purpose:** The post-checkout page. Wait for the **server-verified** entitlement.
* **Interactions:** automatic polling; "Go to My groups" / "Create a group" once premium is active.
* **Components:** Card, Spinner, Alert, Button.
* **API:** `GET /v1/billing/entitlements`, polled every 2 s for up to 60 s.
* **Loading:** "Confirming your payment…"
* **Error:** timeout → "Your payment is being processed. Premium will appear shortly. We'll notify you." with a link to `/membership`.
* **Empty:** n/a.
* **Authorization:** Onboarded. Missing `session_id` → `/membership`.
* **Acceptance criteria:**
  1. The page grants nothing itself. Premium UI unlocks only when `GET /v1/billing/entitlements` reports it (BILL-003, ADR-0012).
  2. Forging `?session_id=` with no real payment never unlocks anything.
  3. **E2E (with a backend):** premium purchase → entitlement active → `/groups/new` allowed (GRP-001).

### P-5.4 My groups

* **Purpose:** The groups the user belongs to, plus pending invitations (brief §18).
* **Interactions:** open a group; see roles and unread chat counts; jump to Invitations; "Create group" (upsell if not premium).
* **Components:** GroupCard (`mine`), Badge (role), EntitlementGate, Button, EmptyState, Tabs (My groups · Invitations · Discover when flagged).
* **API:** `GET /v1/groups?scope=mine&cursor=`; `GET /v1/users/me/group-invitations?count_only=true` *(ind.)*; `GET /v1/billing/entitlements`.
* **Loading:** card skeletons.
* **Error:** inline ErrorState.
* **Empty:** "You're not in any groups yet." Premium users see "Create a group". Free users see "Accept an invitation, or go Premium to create one."
* **Authorization:** Onboarded.
* **Acceptance criteria:**
  1. Free users can see and join groups by invitation (GRP-008), and "Create group" opens the upsell.
  2. Archived groups are shown read-only, labelled "Archived" (GRP-011).

### P-5.5 Discover groups

* **Purpose:** Browse public or listed groups. **Behind flag `groups.public_discovery`** (PRD §1.2, GRP-004).
* **Interactions:** filter by destination, dates and interests; open a preview; join (open groups) or request to join.
* **Components:** GroupCard (`discover`), DestinationAutocomplete, DateRangePicker, ToggleChip, Button, EmptyState.
* **API:** `GET /v1/groups?scope=discover&destination_id=&from=&to=&interests=&cursor=`; `POST /v1/groups/{id}/join-requests`; join `POST /v1/groups/{id}/members/me` *(ind.)*.
* **Loading:** skeletons.
* **Error:** `group_capacity_reached` → disable+why.
* **Empty:** "No public groups match."
* **Authorization:** Onboarded; **404** when the flag is off.
* **Acceptance criteria:**
  1. With the flag off, the route returns 404 and no nav item links to it.
  2. Private groups never appear in results (03 §5.5).

### P-5.6 Group invitations

* **Purpose:** Pending direct invitations, plus invite-link redemption (GRP-005).
* **Interactions:** accept; decline; open a group preview; redeem a link (`?token=`) → confirmation.
* **Components:** GroupCard (`invitation`), Button, AlertDialog, EmptyState.
* **API:** `GET /v1/users/me/group-invitations`; `POST /v1/group-invitations/{id}/accept|decline`; `POST /v1/group-invitations/redeem {token}` *(ind.)*.
* **Loading:** skeletons.
* **Error:** `invitation_invalid` (expired, revoked or max uses) → "This invitation is no longer valid". `group_capacity_reached` → message.
* **Empty:** "No pending invitations."
* **Authorization:** Onboarded.
* **Acceptance criteria:**
  1. A link token is sent only in the POST body, and it is removed from the URL (history replace) after redemption.
  2. Accepting needs no subscription (GRP-008).
  3. Concurrent redemption beyond `max_uses` is rejected (server; T-GRP-02) and shown as invalid.

### P-5.7 Create group

* **Purpose:** Create a premium travel group (brief §18, GRP-001…003).
* **Interactions:** fill name, description, cover image, destination, travel dates, interests, privacy (v1: private, invite-only; others flagged), member capacity (≤ configured max); create.
* **Components:** EntitlementGate (upsell for non-premium), FormField, Input, Textarea, MediaUploader (cover), DestinationAutocomplete, DateRangePicker, ToggleChip, RadioGroup, Input (number), Button.
* **API:** `GET /v1/billing/entitlements`; `POST /v1/groups` with `Idempotency-Key`; media upload.
* **Loading:** form ready immediately; create button `L`.
* **Error:** `403 entitlement_required` (`entitlement: groups.create`) → upsell, even if the UI thought the user was premium. `quota_exceeded` for `groups.owned` (default 10, GRP-013) → message. Validation errors → fields.
* **Empty:** n/a.
* **Authorization:** Onboarded. Creation is gated server-side by `groups.create` (GRP-001); the web gate is a convenience.
* **Acceptance criteria:**
  1. Given a free user who bypasses the UI and posts directly, the API returns `403 entitlement_required` and the page shows the upsell (GRP-001, T-BILL-01).
  2. On success the creator is owner and admin, and lands on the group overview (GRP-002).
  3. Capacity above the configured maximum (default 50) is rejected with a field error.
  4. Retrying after a network error creates one group.

### P-5.8 Group overview

* **Purpose:** The group home: details, announcements, upcoming challenges, itinerary summary, members preview (brief §18).
* **Interactions:** read announcements; jump to tabs (Chat, Members, Challenges, Itinerary); leave group; report group. Invitees see a preview with Accept/Decline.
* **Components:** GroupHeader (tabs), Card (announcement), ChallengeCard (Phase 7), ItineraryDayList (summary), AvatarGroup, DropdownMenu, ReportDialog, EntitlementGate (`lapsed` notice for owner and admins).
* **API:** `GET /v1/groups/{id}` (includes the viewer's role, `premium_grace_until`, `conversation_id`); `GET /v1/groups/{id}/announcements?limit=3` *(ind.)*; `DELETE /v1/groups/{id}/members/me` (leave); `POST /v1/reports`.
* **Loading:** header and section skeletons.
* **Error:** `404` → not found (private group, non-member).
* **Empty:** no announcements → hidden section. A new group shows an "Invite members" prompt for admins.
* **Authorization:** Member or invitee (preview); others **404**.
* **Acceptance criteria:**
  1. A non-member, non-invitee gets 404 for a private group, with no name or member count leaked (T-AZ-02).
  2. Owners and admins of a lapsed group see the grace deadline (`premium_grace_until`). Members never see the owner's billing state (07 §5).
  3. Leaving is always possible, except for the owner, who must transfer ownership or archive first (03 §5.5).

### P-5.9 Group chat

* **Purpose:** Real-time group messaging (brief §19, GCHAT-001…007).
* **Interactions:** send text and photos; reply; react; mention (@handle); see pinned messages; see announcements highlighted; mute the group; report a message. Moderators and admins can also delete messages, pin and unpin, restrict members, and post announcements. "Request private chat" from a member menu sends a **connection request**, not a DM.
* **Components:** MessageThread (`group`, pinned bar), MessageComposer (mention picker), TypingIndicator, MemberList (popover), ReportDialog, ModerationActionDialog (group variant), DropdownMenu.
* **API:** messaging endpoints with the group's `conversation_id` (as P-4.5); `POST /v1/groups/{id}/announcements`; `PUT/DELETE /v1/groups/{id}/pins/{message_id}`; `PATCH /v1/groups/{id}/members/{user_id} {restricted_until}`; `POST /v1/connection-requests`.
* **Loading / Error:** as P-4.5. A restricted member gets "You can read but not send until {date}" (GCHAT-004). Admins-only chat mode → composer hidden for members, with a notice (GCHAT-003).
* **Empty:** "Start the conversation".
* **Authorization:** Member, else **404**.
* **Acceptance criteria:**
  1. Removing a member revokes chat access and the realtime stream immediately. Their open tab shows "You're no longer a member" and receives no further messages (GCHAT-007, T-AZ-03).
  2. Sharing a group never enables a DM. "Request private chat" sends a connection request and respects the recipient's request policy (GCHAT-005, brief §19).
  3. Message deletion by moderators works even after the owner's premium lapses (07 §5, safety never gated).
  4. New members see history according to the group setting (full or from join, GCHAT-006).

### P-5.10 Group members

* **Purpose:** The member list with roles. Admin actions live here.
* **Interactions:** view members and roles; connect (respects policies); report. Admins and moderators can also remove members (by role hierarchy), assign or revoke moderators, change roles, restrict, and transfer ownership (owner only).
* **Components:** MemberList, ConnectionButton, DropdownMenu, AlertDialog, ModerationActionDialog, ReportDialog.
* **API:** `GET /v1/groups/{id}/members?cursor=`; `PATCH /v1/groups/{id}/members/{user_id}`; `DELETE /v1/groups/{id}/members/{user_id}`; `POST /v1/groups/{id}/ownership-transfers`.
* **Loading:** list skeleton.
* **Error:** role-rank violation → "You can't change this member's role" (T-GRP-05).
* **Empty:** n/a (at least the owner).
* **Authorization:** Member, else **404**. Actions per 03 §5.5.
* **Acceptance criteria:**
  1. A moderator cannot promote themselves or act on admins or the owner (T-GRP-05).
  2. Blocked users are filtered out of the viewer's list (03 §5.5).
  3. An ownership transfer is an offer the recipient must accept (expires after 7 days, 07 §5).

### P-5.11 Group itinerary

* **Purpose:** A shared trip linked to the group: read-only in Phase 5, editable by permitted members in Phase 6 (TRIP-005).
* **Interactions:** view days and items; open places on the map; editors can edit as in trip detail.
* **Components:** ItineraryDayList, ItineraryItem, MapView (`itinerary`, lazy), EmptyState.
* **API:** `GET /v1/groups/{id}` (`trip_id`); `GET /v1/trips/{trip_id}`; Phase 6: `PUT /v1/trips/{id}/itinerary` (If-Match).
* **Loading:** skeleton days.
* **Error:** `412` → refresh prompt.
* **Empty:** no linked trip → admins see "Link a trip"; members see "No shared itinerary yet".
* **Authorization:** Member, else **404**. Editing requires the trip editor role.
* **Acceptance criteria:**
  1. Dates render in the destination's time zone (doc 02 §5).
  2. Concurrent edits never silently overwrite. A stale `If-Match` produces a refresh prompt that keeps the local change.

### P-5.12 Group settings

* **Purpose:** Group administration: details, privacy, capacity, invitations (direct and links), join requests, history visibility, chat mode, archive and delete.
* **Interactions:** edit details (If-Match); invite users; create, revoke and inspect invitation links (max uses, expiry, redemptions); approve or reject join requests; configure history visibility and admins-only chat; transfer ownership; archive.
* **Components:** Tabs (Details · Invitations · Requests · Chat · Danger zone), FormField, InvitationManager, AdminDataTable (light), EntitlementGate (`lapsed` blocks premium-only actions with an explanation), AlertDialog.
* **API:** `PATCH /v1/groups/{id}`; `GET/POST /v1/groups/{id}/invitations`; `DELETE /v1/groups/{id}/invitations/{inv_id}`; `GET /v1/groups/{id}/join-requests`; `POST /v1/groups/{id}/join-requests/{rid}/approve|reject`; `POST /v1/groups/{id}/archive`.
* **Loading:** form skeleton.
* **Error:** after the owner's grace period: creating invitations, approving join requests and increasing capacity return `403 entitlement_required`, explained as "Premium features of this group are paused" (07 §5). Safety tools stay enabled.
* **Empty:** no join requests → "No pending requests".
* **Authorization:** Owner or admin (moderators see a limited set); others **404**.
* **Acceptance criteria:**
  1. Invitation links show max uses, expiry and redemption count, and revoking takes effect immediately (T-GRP-03).
  2. After the grace period, the owner can still transfer ownership, archive, edit details and use every safety tool (07 §5 table).
  3. The group is never deleted silently. Archiving warns that members will be notified (GRP-011).

---

## Phase 6 — AI and travel planning

### P-6.1 AI assistant

* **Purpose:** Conversational planning and structured itinerary generation (brief §13, AI-001…009).
* **Interactions:** pick suggested prompts; set destination context, dates and preferences (pace, interests, budget level, travelers); chat; generate an itinerary; preview it; regenerate; modify ("make day 2 more relaxed"); save to a trip (new or existing); share (as a trip share link or a post, TRIP-006); stop generation; see the quota.
* **Components:** AssistantPanel, ItineraryPreview, ItineraryDayList, ItineraryItem (`unverified` badges, "Estimated" labels), MapView (lazy), DestinationAutocomplete, DateRangePicker, ToggleChip, EntitlementGate (`quota`), Button.
* **API:** `POST /v1/ai/itineraries` (→ `generation_id`); `GET /v1/ai/generations/{id}` (poll) or the SSE stream; `POST /v1/ai/chat` (SSE); `POST /v1/trips` + `POST /v1/trips/{id}/apply-itinerary {generation_id}`; `GET /v1/billing/entitlements` (quota `ai.itinerary_generations`).
* **Loading:** streaming tokens and progressive day skeletons; stop button.
* **Error:** `503 ai_unavailable` → "The assistant is unavailable right now. The rest of the app works normally." `429 quota_exceeded` → reset date, plus an upsell for free users (07 §7). Validation failure from the server → "We couldn't produce a reliable itinerary. Try adjusting your request." Mock mode → `feature_not_available_in_mock` honest panel.
* **Empty:** first visit → suggested prompts ("Plan a five-day trip to Rio with beaches, local restaurants, photography spots and adventure activities").
* **Authorization:** Onboarded; quotas server-side.
* **Acceptance criteria:**
  1. Opening hours, ticket availability, live transit, reservation status and safety guarantees are never displayed from AI output. When licensed data supplies them, it is shown with its source and `data_freshness_at` (AI-004, brief §13).
  2. Activities without a catalog `place_id` are labelled "Unverified suggestion" (AI-003). Costs and durations are labelled "Estimated" and appear only when grounded.
  3. Output is shown in the user's UI language (AI-007).
  4. Saving creates an editable trip whose items match the preview (TRIP-002).
  5. No AI provider key or provider URL is present in browser code (brief §13). All calls go through the BFF.
  6. The quota meter matches `quotas.ai.itinerary_generations` from the API.

### P-6.2 My trips

* **Purpose:** The list of trips: upcoming, past, shared with me (TRIP-001/005).
* **Interactions:** filter tabs; open a trip; create a trip; plan with AI.
* **Components:** Tabs, TripCard, Button, EmptyState.
* **API:** `GET /v1/trips?scope=mine|shared&status=upcoming|past&cursor=`.
* **Loading:** card skeletons.
* **Error:** inline ErrorState.
* **Empty:** "No trips yet" + "Create trip" + "Plan with AI".
* **Authorization:** Onboarded.
* **Acceptance criteria:**
  1. Trips created on mobile appear here, and vice versa (synced via the platform, brief §14).
  2. Dates are shown in the destination's time zone.

### P-6.3 Create trip

* **Purpose:** Create a trip with destination, dates, preferences, budget and travelers (brief §14).
* **Interactions:** fill the form; create → trip detail; optional "Generate itinerary with AI".
* **Components:** FormField, DestinationAutocomplete, DateRangePicker, ToggleChip, Select (budget level), Input (travelers), Button.
* **API:** `POST /v1/trips` (Idempotency-Key).
* **Loading:** button `L`.
* **Error:** end before start → field error; validation mapping.
* **Empty:** n/a.
* **Authorization:** Onboarded.
* **Acceptance criteria:**
  1. Budget is captured as a level or amount in the user's currency, and never shown as a verified price.
  2. Retrying after a network error creates one trip.

### P-6.4 Trip detail

* **Purpose:** Trip overview and day-by-day itinerary editing (brief §14).
* **Interactions:** select a day (`?day=`); add places (search, saved places, map); remove activities; edit times and durations; **reorder** by drag-and-drop on desktop, with **Move up/down, "Move to day…" and keyboard reordering** as accessible alternatives; change dates; route preview between items; invite collaborators; share; delete trip.
* **Components:** ItineraryDayList, ItineraryItem, MapView (`itinerary`), Combobox (place search), Dialog, EntitlementGate (`trips` collaborator limit, if configured), AlertDialog, Toast.
* **API:** `GET /v1/trips/{id}`; `PATCH /v1/trips/{id}` and `PUT /v1/trips/{id}/itinerary` with `If-Match`; `GET /v1/destinations/{id}/places`; `GET /v1/users/me/saved-places`; collaborators and share links *(ind.)*; route preview through the platform routing endpoint *(ind.)*.
* **Loading:** skeleton days; the map lazy-loads.
* **Error:** `412 precondition_failed` → "This trip changed on another device" with merge or reload (TRIP-004). Routing unavailable → hide the route, keep the list.
* **Empty:** a day with no items → "Add a place" + suggestions from saved places.
* **Authorization:** Owner or collaborator, else **404**.
* **Acceptance criteria:**
  1. Every reorder possible by drag-and-drop is possible by keyboard and buttons, and each move is announced ("Moved Sugarloaf to position 2 on Day 1").
  2. Edits from mobile appear after refresh or focus, and conflicting edits never silently overwrite (TRIP-004).
  3. Route previews are labelled as estimates from the routing provider (GUIDE-003).
  4. Removing an item offers Undo for 6 s.

### P-6.5 Explore

* **Purpose:** Interactive map-based exploration of destinations and places (brief §12, GUIDE-001).
* **Interactions:** search a destination; filter categories (attractions, restaurants, nature, museums, beaches, activities, saved); pan and zoom (viewport loading); select a marker or list item (synced); open place details; save a place; open featured guides. Mobile: map/list toggle.
* **Components:** split layout (list start, map end), DestinationAutocomplete, ToggleChip, Card list, MapView (`explore`), PlaceMarker / Cluster, SaveButton, Sheet (mobile list or details).
* **API:** `GET /v1/destinations/search`; `GET /v1/destinations/{id}/places?category=&bbox=&cursor=` (debounced 300 ms, ADR-0014); `PUT/DELETE /v1/users/me/saved-places/{place_id}`; `GET /v1/guides?destination_id=`.
* **Loading:** list skeleton; the map chunk lazy-loads with a placeholder; viewport refetch shows a subtle top progress bar.
* **Error:** map style failure → list-only mode with a notice. Places failure → inline ErrorState.
* **Empty:** no places in the viewport for the selected categories → "Nothing here for these filters" + "Zoom out".
* **Authorization:** Onboarded.
* **Acceptance criteria:**
  1. Panning loads places for the new bounding box at most once per 300 ms, and markers cluster at low zoom.
  2. Every place on the map is reachable from the list by keyboard, and selecting a list item focuses its marker and vice versa.
  3. Place details show attribution and data freshness (DEST-003, GUIDE-002).
  4. On mobile, the map/list toggle preserves the selection and scroll position.

### P-6.6 Attraction page

* **Purpose:** A public, indexable page for a catalog place.
* **Interactions:** read the description; view on the map; see attribution and freshness; save (island); open nearby places; add to a trip (gate→login).
* **Components:** DestinationHero (place), MapView (`static`), Card, SaveButton, Button.
* **API:** `GET /v1/places/{id}` *(ind.)*, or lookup by slug through the destination places endpoint.
* **Loading:** n/a (ISR).
* **Error:** 404 → not found.
* **Empty:** n/a.
* **Authorization:** Public.
* **Acceptance criteria:**
  1. Opening hours and prices appear only with source and `data_freshness_at`, and stale data is flagged (DEST-003).
  2. JSON-LD `TouristAttraction` validates.

### P-6.7 Guide library

* **Purpose:** Browse destination guides and audio tours (GUIDE-004/005).
* **Interactions:** filter by destination, free or premium, audio; open a guide.
* **Components:** Card grid (GuideCard), Badge (`premium`, "Audio"), DestinationAutocomplete, ToggleChip, EmptyState.
* **API:** `GET /v1/guides?destination_id=&tier=&has_audio=&cursor=`.
* **Loading:** n/a (ISR) for the default view; filters show client skeletons.
* **Error:** inline ErrorState.
* **Empty:** "No guides for this destination yet."
* **Authorization:** Public (descriptions only).
* **Acceptance criteria:**
  1. Premium items are clearly marked before the user opens them.
  2. Audio asset URLs never appear on public pages or in sitemaps.

### P-6.8 Guide detail

* **Purpose:** Public description of a guide or audio tour, with a path to play it.
* **Interactions:** read the description, stops list (names only) and duration; "Start tour" (gate→login → `/tours/{id}`); premium → upsell; save.
* **Components:** DestinationHero, TourStopList (read-only), Badge, EntitlementGate (island), Button.
* **API:** `GET /v1/guides/{id}` *(ind.)*; `GET /v1/billing/entitlements` (island).
* **Loading:** n/a (ISR).
* **Error:** 404 → not found.
* **Empty:** n/a.
* **Authorization:** Public.
* **Acceptance criteria:**
  1. Free users opening a premium tour see an upsell naming `audio_tours.premium` or the purchasable content item (07 §3).
  2. The page states plainly that automatic playback by location depends on browser support (brief §21).

### P-6.9 Audio tour player

* **Purpose:** Browser audio tour playback (brief §21).
* **Interactions:** play, pause, seek; speed 0.75–2×; previous and next stop; "Play this stop" manually; optional "Play automatically near stops", which needs explicit location permission and works only while the page is open; save the tour; download for offline use (PWA, where supported, within quota); view stops on the map.
* **Components:** AudioPlayer, TourStopList, MapView (`itinerary`), Switch (auto-play near stops), Progress (download), EntitlementGate (`offline.packages` quota), Button.
* **API:** `GET /v1/audio-tours/{id}` (signed audio URLs); `GET /v1/audio-tours/{id}/offline-manifest`; save *(ind.)*; `GET /v1/billing/entitlements`.
* **Loading:** player skeleton; per-stop buffering indicator.
* **Error:** geolocation denied or unsupported → manual stop playback stays fully available, with a notice. Offline download unsupported → hide download and say why. `quota_exceeded` (`offline.packages`) → manage-downloads message.
* **Empty:** n/a.
* **Authorization:** Onboarded. Premium tours need `audio_tours.premium` or purchased content (server). Device location stays in the browser for stop triggering and is **never sent** to the server (GUIDE-005).
* **Acceptance criteria:**
  1. Every stop can be played manually without location permission (brief §21).
  2. Location-triggered playback never transmits coordinates to the platform, verified by inspecting network traffic in an E2E test (GUIDE-005).
  3. Offline downloads verify per-file SHA-256 from the signed manifest and respect `offline.packages` (OFF-001, OFF-004).
  4. The page never claims background playback or geofencing when the tab is closed or backgrounded.
  5. Speed control and seek are keyboard-operable with labelled controls, and a transcript is available when provided.

---

## Phase 7 — Gamification

### P-7.1 Challenge dashboard

* **Purpose:** The group's challenges by status: Active, Upcoming, Completed (brief §20).
* **Interactions:** switch status tabs (`?status=`); open a challenge. Admins can also create a challenge (EntitlementGate).
* **Components:** Tabs, ChallengeCard, EntitlementGate, Button, EmptyState.
* **API:** `GET /v1/groups/{id}/challenges?status=active|upcoming|completed&cursor=`; `GET /v1/billing/entitlements` (admins).
* **Loading:** card skeletons.
* **Error:** inline ErrorState.
* **Empty:** per tab: "No active challenges". Admins also get "Create a riddle".
* **Authorization:** Group member, else **404**. Creation needs a group role with challenge management, `challenges.create` on the creator, **and** active group premium (07 §3.1, §5; CHAL-001).
* **Acceptance criteria:**
  1. Upcoming challenges show only the title and start time, not the riddle (03 §5.6).
  2. After the owner's premium grace ends, the create button shows "Premium features of this group are paused". Running challenges continue to completion (07 §5).

### P-7.2 Challenge detail

* **Purpose:** View a riddle, request hints, submit answers, collaborate, see results (brief §20, CHAL-002…016). Admins create and judge here.
* **Interactions:**
  * Participant: read the riddle and media; request hints (per schedule); submit an answer (individual, or team captain only); join or create a team; discuss in the challenge thread; view attempts left and cooldown; view results (winner, team, award, completion timestamp, summary); open a dispute.
  * Admin: edit the draft (ChallengeEditor), publish or schedule, cancel, review `needs_review` submissions (CHAL-007), publish results, see fulfilment status.
* **Components:** RiddleSubmission, HintReveal, ChallengeEditor, MessageThread (challenge discussion), Card (results), Badge, AlertDialog, ReportDialog.
* **API:** `GET /v1/challenges/{id}`; `PATCH /v1/challenges/{id}` (If-Match, admins); `POST /v1/challenges/{id}/publish`; `POST /v1/challenges/{id}/hints/{n}/reveal`; `POST /v1/challenges/{id}/submissions` (Idempotency-Key); `GET /v1/challenges/{id}/submissions/me`; `GET/POST /v1/challenges/{id}/teams`, `POST …/teams/{tid}/join`; `GET /v1/challenges/{id}/results`; `POST /v1/challenges/{id}/judgements` (admins) *(ind.)*; `POST /v1/challenges/{id}/disputes`.
* **Loading:** detail skeleton; submit button `L`.
* **Error:** `challenge_not_active` → disable+why with the start or end time. `attempts_exhausted` → "No attempts left". Cooldown `rate_limited` → countdown. Non-captain submission refused → "Only your team captain can submit" (CHAL-004). Admin config errors (CHAL-002/013, e.g. a prohibited cash reward) → field errors.
* **Empty:** results not yet published → "Results will be announced after judging".
* **Authorization:** Group member, else **404**. Authors cannot submit to their own challenge (03 §5.6).
* **Acceptance criteria:**
  1. Neither the member view nor its network responses contain answer fields or judging criteria at any point (CHAL-008, T-CHAL-01). The editor's answer fields are write-only.
  2. Feedback on a submission is only "Correct" or "Not correct", with attempts left from the server (CHAL-005).
  3. Submission timestamps shown are server timestamps. Winner order is deterministic and matches the server result (CHAL-009).
  4. The prize editor accepts only badges, recognition and documented non-cash promotional rewards. Paid entry, raffles, wagers and cash or cash-equivalent rewards are rejected (CHAL-012/013, brief §20 MVP).
  5. Real-world rewards cannot be published until review is approved, and the UI shows "Awaiting platform review" (CHAL-014).
  6. Opening a dispute is always available to participants and never paywalled (03 §5.6).

### P-7.3 Badges

* **Purpose:** Earned badges and achievements (CHAL-012).
* **Interactions:** view badges; open badge detail (challenge, group, date); toggle "show on profile".
* **Components:** Card grid, Badge, Dialog, Switch.
* **API:** `GET /v1/users/me/badges` *(ind.)*; profile setting via `PATCH /v1/users/me/privacy`.
* **Loading:** grid skeleton.
* **Error:** inline ErrorState.
* **Empty:** "Win challenges in your groups to earn badges."
* **Authorization:** Onboarded (own).
* **Acceptance criteria:**
  1. Badges from private groups do not reveal the group name on the public profile.
  2. Badges are non-transferable and have no monetary value shown (CHAL-012/013).

---

## Phase 8 — Administration

All admin pages: **Staff** with the permission from [02 §2.4](02-routes-and-sitemap.md#24-admin--admin-not-indexable) / [03 §4](03-roles-permissions.md#4-platform-roles-staff), else **404**. Every action is audited by the backend (SAFE-007). The web shows "This action is logged" on action dialogs.

### P-8.1 Admin overview

* **Purpose:** Business and operational overview (brief §24): registered users, active users, new subscriptions, paid conversion, revenue, published posts, active groups, pending reports, operational alerts (ADM-006).
* **Interactions:** choose a time range; open drill-downs (reports queue, billing events); acknowledge an alert *(ind.)*.
* **Components:** MetricTile, Select (range), Alert list, AdminDataTable (alerts), Card.
* **API:** `GET /v1/admin/metrics/overview?range=` (includes alerts, or `GET /v1/admin/alerts` *(ind.)*).
* **Loading:** tile skeletons.
* **Error:** per-tile `unavailable` state, "Metric unavailable". A number is **never** fabricated or estimated client-side (brief §24).
* **Empty:** no alerts → "No active alerts".
* **Authorization:** `ADMIN_ACCESS`. Tiles are filtered by `METRICS_READ`: revenue and conversion for admin and superadmin only; moderation metrics for moderators; operational metrics for support (03 §4).
* **Acceptance criteria:**
  1. Every tile value equals the API value. With the API down, tiles show "Metric unavailable", not zeros.
  2. A moderator sees no revenue or conversion tiles, and their values are absent from the response.
  3. Mock mode labels every tile "Mock data".

### P-8.2 User search

* **Purpose:** Find accounts (ADM-003).
* **Interactions:** search by handle, display name, user ID (email search only with `USERS_READ_PII`); filter by status; open a user.
* **Components:** Input (search), Select (status), AdminDataTable.
* **API:** `GET /v1/admin/users?q=&status=&cursor=`.
* **Loading:** table skeleton.
* **Error:** inline ErrorState.
* **Empty:** "No users match."
* **Authorization:** `USERS_READ_BASIC`.
* **Acceptance criteria:**
  1. Results show no email unless the viewer holds `USERS_READ_PII` and has revealed it on the detail page.
  2. The search query is not written to client logs or analytics.

### P-8.3 User detail

* **Purpose:** The account view: status, dates, reports about and by the user, moderation history, sessions summary; actions (ADM-002/003).
* **Interactions:** reveal PII with a justification (`USERS_READ_PII`); suspend, reinstate or restrict with a reason code and duration (`USERS_SUSPEND` / `MODERATION_ACTION`); view moderation history; execute deletion after the DSR grace period (`USERS_DELETE`); grant a promotional entitlement (BILL-009, superadmin, audited).
* **Components:** Card, Tabs (Overview · Reports · History · Billing), PiiReveal, ModerationActionDialog, AuditLogTable (filtered), AlertDialog.
* **API:** `GET /v1/admin/users/{id}`; `POST /v1/admin/users/{id}/pii-access {reason}` *(ind.)*; `POST /v1/admin/moderation-actions`; `GET /v1/admin/users/{id}/moderation-history` *(ind.)*; `GET /v1/admin/audit-logs?resource=user:{id}`.
* **Loading:** section skeletons.
* **Error:** 404 → not found.
* **Empty:** no history → "No moderation history".
* **Authorization:** `USERS_READ_BASIC`; actions per permission.
* **Acceptance criteria:**
  1. PII is hidden by default. Revealing requires a non-empty reason, and the audit log records it (ADM-003, doc 08 T-AZ-07).
  2. Message content is not viewable here (only reported evidence on report pages, T-AZ-07).
  3. Suspension requires a reason code and shows a preview of the user-facing notice and appeal path (03 §8).
  4. Coordinates are never shown, because the platform does not store them (LOC-001).

### P-8.4 Report queue

* **Purpose:** The prioritized moderation queue (SAFE-003, ADM-002).
* **Interactions:** filter by target type (post, comment, user, message, group, challenge), priority, status, assignee; sort by priority then age; assign to self; open a report.
* **Components:** AdminDataTable, Select, ToggleChip, Badge (priority), Button.
* **API:** `GET /v1/admin/reports?status=&target_type=&priority=&assignee=&cursor=`; `POST /v1/admin/reports/{id}/assign` *(ind.)*.
* **Loading:** table skeleton.
* **Error:** inline ErrorState.
* **Empty:** "Queue is clear."
* **Authorization:** `REPORTS_READ`.
* **Acceptance criteria:**
  1. Minor safety, self-harm and threat reports sort first by default (SAFE-003).
  2. The queue shows the SLA age for priority reports (G-3 target < 2 h).

### P-8.5 Report review

* **Purpose:** Review a report with its evidence snapshot and take action.
* **Interactions:** view the evidence snapshot (content as reported, even if later edited or deleted), reporter reason, target history, related reports; act: remove, limit, warn, restrict, suspend, ban, reinstate, dismiss (ADM-002); write a note; resolve.
* **Components:** Card (evidence), AuditLogTable (target), ModerationActionDialog, Textarea, Button.
* **API:** `GET /v1/admin/reports/{id}`; `POST /v1/admin/moderation-actions`; `POST /v1/admin/reports/{id}/resolve` *(ind.)*.
* **Loading:** skeleton.
* **Error:** 404 → not found. Concurrent resolution → "Already resolved by {staff}".
* **Empty:** n/a.
* **Authorization:** `REPORTS_READ`; actions need `MODERATION_ACTION`.
* **Acceptance criteria:**
  1. Media evidence renders through short-lived signed URLs only.
  2. Every action requires a reason code from the community-guidelines taxonomy, and the author is shown that reason (03 §8).
  3. The reporter's identity is never exposed to the reported user through any user-facing surface (A7).

### P-8.6 Appeals

* **Purpose:** Review appeals against moderation decisions.
* **Interactions:** filter; open an appeal (original action, evidence, the user's statement); uphold or overturn with a note.
* **Components:** AdminDataTable, Card, ModerationActionDialog (appeal variant).
* **API:** `GET /v1/admin/appeals?status=&cursor=`; `POST /v1/admin/appeals/{id}/decision` *(ind.)*.
* **Loading:** skeleton.
* **Error:** inline.
* **Empty:** "No pending appeals."
* **Authorization:** `APPEALS_DECIDE`. Moderators cannot decide appeals on their own actions (03 §4); the decide control is hidden and the server rejects it.
* **Acceptance criteria:**
  1. The original decision maker cannot decide the appeal, in the UI or the API.
  2. Overturning reinstates the content or account and notifies the user.

### P-8.7 Groups under review

* **Purpose:** Groups with reports or abuse signals.
* **Interactions:** filter (reported, suspended, signal type); open a group.
* **Components:** AdminDataTable, Badge.
* **API:** `GET /v1/admin/groups?flagged=true&status=&cursor=`.
* **Loading / Error / Empty:** table skeleton; inline error; "No groups under review."
* **Authorization:** `REPORTS_READ` (02 Q6).
* **Acceptance criteria:**
  1. Rows show the report count, latest report reason and status without exposing chat content.

### P-8.8 Group investigation

* **Purpose:** Investigate a group: metadata, membership size, roles, reports, reported messages (evidence only), moderation history; suspend or reinstate.
* **Interactions:** view; suspend or reinstate with a reason (`GROUPS_SUSPEND`); handle permitted disputes; open related reports.
* **Components:** Card, Tabs, AuditLogTable, ModerationActionDialog.
* **API:** `GET /v1/admin/groups/{id}`; `POST /v1/admin/moderation-actions` (target group).
* **Loading / Error / Empty:** skeleton; 404; "No reports".
* **Authorization:** `REPORTS_READ`; actions need `GROUPS_SUSPEND`.
* **Acceptance criteria:**
  1. Full chat history is not browsable. Only reported messages appear, as evidence (T-AZ-07).
  2. Suspension notifies the owner and admins with the reason and appeal path, and the data is preserved (GRP-011).

### P-8.9 Challenge review

* **Purpose:** Review reported challenges, suspicious submissions (multi-account, scripted), and rewards awaiting platform review (CHAL-014).
* **Interactions:** filter (reported, fraud signal, reward review); open the challenge with its submissions and server timestamps; approve or reject a reward review; suspend the challenge; act on accounts.
* **Components:** AdminDataTable, Card, ModerationActionDialog, Badge.
* **API:** `GET /v1/admin/challenges?flagged=&review_status=&cursor=`; `GET /v1/admin/challenges/{id}/submissions` *(ind.)*; `POST /v1/admin/challenges/{id}/reward-review {decision}` *(ind.)*; `POST /v1/admin/moderation-actions`.
* **Loading / Error / Empty:** skeleton; inline; "Nothing to review".
* **Authorization:** `CHALLENGES_REVIEW`.
* **Acceptance criteria:**
  1. Submission lists show server timestamps and device-signal flags. Answers are visible only to roles holding the judge permission, and access is audited (CHAL-008).
  2. Rewards with monetary patterns are flagged for review (CHAL-013).

### P-8.10 Prize disputes

* **Purpose:** Resolve escalated prize disputes and track reward fulfilment (CHAL-015/016).
* **Interactions:** open a dispute (claim, evidence, group admin decision); resolve; transition fulfilment state (pending → issued → delivered, failed, cancelled, disputed) with `REWARDS_FULFIL`.
* **Components:** AdminDataTable, Card, Select (state transition), Textarea, AlertDialog.
* **API:** `GET /v1/admin/challenges/disputes?status=&cursor=`; `POST /v1/admin/challenges/disputes/{id}/resolve` *(ind.)*; `POST /v1/admin/reward-fulfillments/{id}/transition` *(ind.)*.
* **Loading / Error / Empty:** skeleton; inline; "No open disputes".
* **Authorization:** `CHALLENGES_REVIEW`; fulfilment transitions need `REWARDS_FULFIL`.
* **Acceptance criteria:**
  1. Only valid state-machine transitions are offered, and the server rejects invalid ones (CHAL-015).
  2. Each transition records an actor and note, visible in the audit log.

### P-8.11 Destination catalog

* **Purpose:** Manage destinations and featured placement (DEST-004, ADM-004).
* **Interactions:** search and filter (kind, country, published, featured, content threshold); open or create; feature or unfeature.
* **Components:** AdminDataTable, Input, Select, Switch (featured), Button.
* **API:** `GET /v1/admin/destinations?q=&kind=&published=&featured=&cursor=`; `PUT /v1/admin/destinations/{id}/featured` *(ind.)*.
* **Loading / Error / Empty:** skeleton; inline; "No destinations match".
* **Authorization:** `DESTINATIONS_EDIT`.
* **Acceptance criteria:**
  1. Featuring and unfeaturing are audited (DEST-004), and the public homepage reflects them after revalidation.

### P-8.12 Destination editor

Routes: `/admin/destinations/new`, `/admin/destinations/[destinationId]`.

* **Purpose:** Create and edit destination records: slug, hierarchy (parent), names and localizations, overview copy per locale, hero image with credit and licence, highlights, FAQs, publish state.
* **Interactions:** edit per-locale tabs; upload a hero image (licence and credit required); preview the public page; publish or unpublish; save (If-Match).
* **Components:** Tabs (per locale), FormField, Input, Textarea (Markdown-limited), MediaUploader, Combobox (parent destination), Switch (published), Button, Dialog (preview).
* **API:** `POST /v1/admin/destinations`; `GET/PATCH /v1/admin/destinations/{id}` (If-Match); `PUT /v1/admin/destinations/{id}/localizations/{locale}` *(ind.)*; media upload.
* **Loading:** form skeleton.
* **Error:** slug conflict → field error. A slug change warns that a redirect will be created (02 Q4). `412` → reload prompt.
* **Empty:** n/a.
* **Authorization:** `DESTINATIONS_EDIT`.
* **Acceptance criteria:**
  1. Publishing with a hero image is impossible without credit and licence (01 §14).
  2. Saving triggers revalidation of the destination's public pages (by tag).
  3. Rich text is sanitized server-side, and the editor never uses `dangerouslySetInnerHTML` for previews (T-INJ-02).

### P-8.13 Guide review

* **Purpose:** Review and publish guide and audio content (ADM-004, GUIDE-004).
* **Interactions:** list guides and tours by status; open; review text, audio stops and licences; set tier (free or premium); publish or unpublish.
* **Components:** AdminDataTable, Card, AudioPlayer (review), Select, Switch.
* **API:** `GET/PATCH /v1/admin/guides[/{id}]` *(ind.)*.
* **Loading / Error / Empty:** skeleton; inline; "No guides awaiting review".
* **Authorization:** `GUIDES_EDIT`.
* **Acceptance criteria:**
  1. Content with an expired licence cannot be published (OFF-005).

### P-8.14 Subscriptions

* **Purpose:** View subscription status across providers (Apple, Google, Stripe).
* **Interactions:** search by user; filter by provider and state; open a subscription (history of state transitions, linked billing events).
* **Components:** AdminDataTable, Select, Badge, Card.
* **API:** `GET /v1/admin/billing/subscriptions?q=&provider=&status=&cursor=`.
* **Loading / Error / Empty:** skeleton; inline; "No subscriptions match".
* **Authorization:** `BILLING_READ`.
* **Acceptance criteria:**
  1. No card numbers, full payment credentials or store receipts are ever displayed (brief §24).
  2. States use the normalized 07 §4 vocabulary.

### P-8.15 Entitlement mappings

* **Purpose:** View and (superadmin) configure product → entitlement mappings and quota settings (ADM-005).
* **Interactions:** view mappings per platform product; edit with a change preview (superadmin); save.
* **Components:** AdminDataTable, Dialog (change preview), Input, Button.
* **API:** `GET/PUT /v1/admin/billing/entitlement-mappings` *(ind.)*.
* **Loading / Error / Empty:** skeleton; inline; n/a.
* **Authorization:** view `BILLING_READ`; edit `BILLING_CONFIGURE` (superadmin only).
* **Acceptance criteria:**
  1. Edits show a diff preview, require confirmation, and are audited (03 §8).
  2. Non-superadmins see read-only values with no edit controls, and the API rejects their edits.

### P-8.16 Billing events

* **Purpose:** Inspect provider notifications and webhook processing, and monitor payment failures.
* **Interactions:** filter by provider, type, processing status (processed, ignored, failed) and date; open an event (normalized payload without secrets); view the failure reason.
* **Components:** AdminDataTable, Card (JSON viewer, redacted), Select.
* **API:** `GET /v1/admin/billing/events?provider=&status=&type=&from=&to=&cursor=`.
* **Loading / Error / Empty:** skeleton; inline; "No events in this range".
* **Authorization:** `BILLING_READ`.
* **Acceptance criteria:**
  1. Payloads are displayed redacted, with no tokens, signatures or card data.
  2. A failed-processing filter lists events with their retry state (BILL-006).

### P-8.17 Audit log

* **Purpose:** Read the append-only audit log (SAFE-007).
* **Interactions:** filter by actor, action, resource and date range; open an entry; copy IDs; export the filtered range (CSV, audited) *(ind.)*.
* **Components:** AuditLogTable, Input, DateRangePicker, Select.
* **API:** `GET /v1/admin/audit-logs?actor=&action=&resource=&from=&to=&cursor=`.
* **Loading / Error / Empty:** skeleton; inline; "No entries".
* **Authorization:** `AUDIT_READ`.
* **Acceptance criteria:**
  1. The UI offers no edit or delete for entries (append-only).
  2. Viewing and exporting are themselves audited.

---

## Phase 9 — Production readiness

### P-9.1 Data and account deletion

* **Purpose:** Data-subject rights: export my data (AUTH-011) and delete my account (AUTH-010).
* **Interactions:** request an export (async, emailed link valid 7 days); see export status; request deletion (re-authentication through the IdP, typed confirmation phrase, explanation of the 30-day reversible grace period); cancel a pending deletion.
* **Components:** Card, Button, AlertDialog (typed confirmation), Alert, Badge (status).
* **API:** `POST /v1/users/me/data-exports` *(ind.)*; `GET /v1/users/me/data-exports` *(ind.)*; `POST /v1/users/me/deletion` / `DELETE /v1/users/me/deletion` *(ind.)*.
* **Loading:** button `L`; status skeleton.
* **Error:** export already in progress → status shown; re-auth failure → stays on the page.
* **Empty:** no previous exports → "You haven't requested an export".
* **Authorization:** Session (own); never paywalled (03 §5.8).
* **Acceptance criteria:**
  1. Deletion requires recent re-authentication and the typed phrase. On success the user is signed out and the deletion date is shown (AUTH-010).
  2. Signing in during the grace period offers "Cancel deletion" (shell banner, 02 rule 14a).
  3. Export readiness is communicated within 72 h, and the link expires after 7 days (AUTH-011).

---

## Open questions

| # | Question | Proposed resolution |
|---|---|---|
| Q1 | **Default post visibility.** The brief requires an explicit choice before a post becomes a public, indexable story. PROF-007 makes the default come from privacy settings, and POST-008 lists four visibilities. | The initial account default is `followers`. Public is never silently preselected, and choosing it shows the search-engine notice (P-3.3 criterion 3). Product to confirm, since this trades cold-start content volume for privacy. |
| Q2 | **IdP hand-offs not in 01 §10.5.** Password reset (P-1.3) and verification-email resend (P-1.4) need BFF entry points. | Extend `GET /api/auth/login` with `intent=reset`, and add `POST /api/auth/verification-email` behind the `IdentityProvider` port. 01 §10.5 and 06 to add them. |
| Q3 | **Decline visibility.** PRD Q-4 defaults to the requester seeing `declined`. Web 03 §5.3 says decline is silent to the requester. | This doc follows PRD Q-4 (P-4.2 criterion 2). 03 to align, or product to decide. |
| Q4 | **DM rule.** DM-001 limits DMs to connected users (`connection_required`). Web 03 §5.3 also allows DMs when the target's setting is `everyone`. | This doc follows DM-001. 03 should drop the `everyone` case for v1. |
| Q5 | **Entitlement keys in 03.** Web 03 §2 uses keys and numbers (for example `groups.admin.advanced`, AI 3/50) that differ from 07 §3 (agreed contract: AI 5/60, `offline.packages` 1/15, `groups.owned` 0/10). | 03 to adopt the 07 keys and reference 07 for numbers. |
| Q6 | **Visibility and moderation vocabulary.** The coordinator contract says public stories are "public + approved". 03 §5.1 says "author opted in, not removed". | Treat `visibility=public` as the author's opt-in and `moderation=approved` as the gate. 03 to reword. |
| Q7 | **Indicative endpoints.** Sub-resource paths marked *(ind.)* (bookmarks list, feed feedback, comment delete, group invitations and joins, challenge teams and judgements, admin sub-resources, data exports, saved tours, badges) are not in 01 §11. | 06 and `contracts/openapi` to fix the names; this doc updates to match. |
| Q8 | **Signed-in profile view** (`/u/[handle]`). | See 02 Q2: recommend an authenticated `/people/[handle]` route. |
| Q9 | **Guest cap on story lists** (AUTH-012) vs SEO. | See 02 Q8. |
| Q10 | **Public group discovery** is a v1 non-goal (PRD §1.2) but appears in the brief. | Flagged route (02 Q7, P-5.5). |
