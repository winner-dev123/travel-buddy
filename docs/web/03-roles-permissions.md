# Web 03 — User Roles and Permission Matrix

| | |
|---|---|
| **Status** | Draft v1.1 — Web Phase 1 |
| **Owner** | Architecture (web) · Security |
| **Builds on** | [PRD §3 access matrix](../01-prd.md#3-user-roles-and-access-matrix) · [doc 02 §9 Authorization model](../02-system-architecture.md#9-authorization-model) · [07 — Subscription and entitlement policy](../07-subscription-entitlement-policy.md) (normative for entitlements) · [08 — Threat model](../08-privacy-security-threat-model.md) · [ERD](../04-database-erd.md) · [Web 01](01-architecture.md) · [ADR-0010](../adr/0010-nextjs-for-web-and-admin.md) |

**Rule zero:** every cell in this document describes a decision the **backend** makes. The "web behaviour" column only says how the UI reflects that decision. Hiding, disabling or upselling a control is never the control itself. Every web check is repeated server-side, so a web bug can produce a worse UX but never a privilege.

This document expands the PRD's coarse access matrix (PRD §3) into the per-capability detail the web needs to render states correctly. Where it touches entitlements, **doc 07 is normative** and this document only references it.

---

## 1. Actors and dimensions

Permission is the intersection of six independent dimensions. A single request can involve all of them (for example "premium user, email verified, admin of group G, connected to user U, not blocked").

| Dimension | Values | Source of truth | In access token? |
|---|---|---|---|
| **Authentication** | `anonymous` (PRD "Guest"), `registered` | `identity` platform session | Yes (`sub`, `sid`) |
| **Account status** (ERD `users.status`) | `active`, `suspended`, `deactivated`, `pending_deletion`, `deleted` | `identity` | `ver` claim forces a refresh on change |
| **Account restrictions** (moderation action `restrict`) | none, or time-boxed limits (no posting / commenting / requests) | `trust_safety.moderation_actions` | No |
| **Email verification** | `email_verified_at` set or null | `identity` (mirrored IdP claim) | No |
| **Entitlements** (premium is *not* a role) | `plan` + features + quotas + content grants ([07 §3](../07-subscription-entitlement-policy.md#3-features-and-quotas)) | `billing.service.has()` / `quota()` | **No**. Evaluated per request, cached 60 s |
| **Relationship to another user** | `self`, `none`, `request_sent`, `request_received`, `connected`, `declined`, `following`, `follow_requested`, blocked (either direction) | `connections.relationship(a,b)`, `trust_safety.is_blocked(a,b)` | No |
| **Group role** (resource-scoped) | `owner`, `admin`, `moderator`, `member`; membership status `active`, `restricted`, `removed`, `left`; plus `invited` (pending invitation) | `groups.group_permissions(user, group)` | **Never** (doc 02 §8) |
| **Platform role** | `support`, `moderator`, `admin`, `superadmin` | `identity.admin_role_assignments` | Yes (`roles`) |

**Blocks always win.** A block in either direction denies every social interaction between the two users (SAFE-001, CONN-009), regardless of entitlements, group roles or connection state. The only exception is platform staff acting through `/admin`, and every such access is audited (T-AZ-07).

**Entitlements never override privacy** ([07 §1](../07-subscription-entitlement-policy.md#1-principles)). Premium cannot bypass blocks, privacy settings, the connection requirement for DMs, rate limits or moderation.

## 2. Entitlements used by the web (summary of doc 07)

`billing.service.has(user, Feature)` and `quota(user, Quota)` are the only gates. The web reads `GET /v1/billing/entitlements` ([07 §7](../07-subscription-entitlement-policy.md#7-entitlements-api-shape-contract)) **only** to render upsells, quota meters and badges.

| Key | Kind | Free | Premium | Web surfaces |
|---|---|---|---|---|
| `groups.create` | feature | ✗ | ✓ | `/groups/new` upsell (GRP-001) |
| `challenges.create` | feature | ✗ | ✓ | Challenge composer. Also needs a group role with `challenges.manage` **and** active group premium ([07 §5](../07-subscription-entitlement-policy.md#5-group-premium-features-and-owner-lapse-grp-009)) |
| `guides.premium` | feature | ✗ | ✓ | Premium guide lock (GUIDE-004) |
| `audio_tours.premium` | feature | ✗ | ✓ | Premium audio tour lock |
| `ai.trip_replan` | feature | ✗ | ✓ | "Replan trip" action (AI-005) |
| `content:guide:<id>`, `content:audio_tour:<id>` | content grant | purchased | purchased | Unlocks one item regardless of plan |
| `ai.itinerary_generations` | quota / month | 5 | 60 | Quota meter on the assistant (AI-009) |
| `ai.trip_replans` | quota / month | 0 | 60 | |
| `offline.packages` | quota (concurrent) | 1 | 15 | PWA downloads manager (OFF-004) |
| `groups.owned` | quota (concurrent) | 0 | 10 | `/groups/new` (GRP-013) |

Numbers are configuration (`ENTITLEMENT_*`), not code. The web never hard-codes them; it renders `limit`/`used` from the API.

**Denials:** a missing feature returns `403 entitlement_required` with an `entitlement` member. An exhausted quota returns `429 quota_exceeded` with `quota`, `limit` and `resets_at`. That is distinct from `429 rate_limited` and the web must treat them differently (07 §7).

**Never behind a paywall** (07 §1.5, §5): block, report, mute, leave group, delete own content, privacy settings, data export, account deletion, group safety tools (remove messages, restrict or remove members, handle reports), ownership transfer, and challenge disputes.

**Group premium derives from the owner** (07 §5). The web renders group admin controls from `viewer_permissions` returned by `GET /v1/groups/{id}`, and shows `premium_grace_until` to owners and admins only (members are never told about the owner's billing state).

## 3. How the web reflects a decision

| Behaviour code | Meaning | When to use |
|---|---|---|
| **show** | Render normally | Allowed |
| **hide** | Do not render the control | The actor can never do it in this context, and the control would only confuse (for example "Remove member" for a plain member) |
| **disable+why** | Render disabled with an explanation | A transient condition the user can see: capacity reached, attempts exhausted, challenge not active, email unverified |
| **upsell** | Render, and on use open the membership sheet | Missing entitlement the user can buy (`entitlement_required`) |
| **quota** | Render with a meter; when exhausted show the reset date (premium) or an upsell (free) | `quota_exceeded` |
| **gate→login** | Render; on use, redirect to `/login?next=…` | Anonymous visitor on a public page |
| **verify-email** | Render; on use, show the "Verify your email" prompt with a resend action | `403 email_unverified` (AUTH-004) |
| **404** | Render the not-found page | Existence must not leak (private group, blocked profile, conversation you are not in). Mirrors the backend rule (doc 02 §5) |
| **403 page** | "You don't have access" | Only where existence is already known to the viewer |

The problem `code` drives the reaction (full mapping in [06 §8](06-api-integration.md#8-error-to-ui-mapping)).

## 4. Platform roles (staff)

Roles are additive: a higher role includes all permissions of the roles to its left. Backend policy: `require_platform_permission(Permission.X)` on every `/v1/admin/*` route (doc 02 §9, ADM-001).

| Permission (`Permission.*`) | support | moderator | admin | superadmin |
|---|---|---|---|---|
| `ADMIN_ACCESS` (enter `/admin`) | ✓ | ✓ | ✓ | ✓ |
| `USERS_READ_BASIC` (search, status, account dates, report history) | ✓ | ✓ | ✓ | ✓ |
| `USERS_READ_SENSITIVE` (email, sign-in methods, sessions) with a just-in-time justification (ADM-003, T-AZ-07) | ✓ | ✗ | ✓ | ✓ |
| `USERS_SUSPEND` / reinstate / ban | ✗ | ✓ | ✓ | ✓ |
| `USERS_DELETE` (execute a data-subject deletion) | ✗ | ✗ | ✓ | ✓ |
| `REPORTS_READ` | ✓ | ✓ | ✓ | ✓ |
| `MODERATION_ACTION` (remove, limit, warn, restrict) (ADM-002) | ✗ | ✓ | ✓ | ✓ |
| `APPEALS_DECIDE` (not on one's own action) | ✗ | ✓ | ✓ | ✓ |
| `GROUPS_SUSPEND` | ✗ | ✓ | ✓ | ✓ |
| `CHALLENGES_REVIEW` (fraud, disputes, AI-judged results) | ✗ | ✓ | ✓ | ✓ |
| `REWARDS_REVIEW` (real-world reward review gate, fulfilment) (CHAL-014/015) | ✗ | ✗ | ✓ | ✓ |
| `DESTINATIONS_EDIT` / `GUIDES_EDIT` / featured placement (ADM-004, DEST-004) | ✗ | ✗ | ✓ | ✓ |
| `BILLING_READ` (subscription status, billing events, failures; **never** card data) | ✓ | ✗ | ✓ | ✓ |
| `BILLING_CONFIGURE` (products, entitlement mappings, quotas, grace) (ADM-005) | ✗ | ✗ | ✗ | ✓ |
| `PROMO_GRANT` (promotional entitlements, audited) (BILL-009) | ✗ | ✗ | ✓ | ✓ |
| `METRICS_READ` (business overview, revenue) | ✗ | ✗ | ✓ | ✓ |
| `OPS_READ` (moderation SLAs, outbox lag, job failures) (ADM-006) | ✓ | ✓ | ✓ | ✓ |
| `AUDIT_READ` | ✗ | ✗ | ✓ | ✓ |
| `ROLES_ASSIGN` | ✗ | ✗ | ✗ | ✓ (two-person rule, §8) |
| `FEATURE_FLAGS_EDIT` | ✗ | ✗ | ✗ | ✓ |

**Web behaviour:** the admin navigation shows only sections whose permission the viewer holds. Direct navigation to a section without permission renders **404** (not 403), so lower roles do not learn the admin surface map. Non-staff users get 404 for all of `/admin/**`. Platform admins have no special powers in the traveler UI (PRD §3: platform admins do not use AI, discovery or DMs as staff).

The permission names above are the web's proposal. The backend `Permission` enum is authoritative (see §10).

## 5. Traveler capability matrix

Legend: ✓ allowed · ✗ denied · **C** conditional (see the policy column) · — not applicable.
Columns: **Anon** = anonymous visitor (PRD Guest); **Free** = registered, active, email verified, no premium; **Prem** = registered with the relevant entitlement.

### 5.1 Public content, feed and posts

| Capability | Anon | Free | Prem | Backend policy | Web behaviour |
|---|---|---|---|---|---|
| Public pages (home, destinations, pricing, legal) | ✓ | ✓ | ✓ | public read model | show |
| Public story (`visibility=public`, `published`, not removed) | ✓ | ✓ | ✓ | `social.can_view(viewer, post, …)` | Anything else → **404** (`noindex`) |
| Capped public post list (≤ 20 per destination, AUTH-012) | ✓ | ✓ | ✓ | public feed cap | "Sign up to see more" after the cap |
| Feed `/feed` (all tabs) | ✗ | ✓ | ✓ | `feed.get_feed(viewer, …)` → `social.visible_posts_for(viewer)` | Anon → `/login?next=/feed` |
| "Nearby" tab with device location | ✗ | **C** | **C** | Only after browser permission granted by an explicit user action. `near` is request-scoped, rounded and never stored (LOC-003); stale > 15 min rejected (LOC-007) | "Use my location" button; denial falls back to the selected destination |
| Create post | ✗ | **C** | **C** | `social.create_post`: `active`, email verified (AUTH-004), not restricted, rate limit, media `ready` | Unverified → verify-email; restricted → disable+why |
| Choose post location precision (none / destination / place) | — | ✓ | ✓ | default from `post_location_default` (POST-002) | Composer selector |
| Edit / delete own post | — | ✓ | ✓ | author == principal (POST-007) | Only on own posts |
| React / comment | gate→login | **C** | **C** | `social.can_view` + not blocked both ways + email verified for comments | |
| Bookmark | gate→login | ✓ | ✓ | `social.can_view` | Optimistic toggle |
| Share | ✓ (public posts) | **C** | **C** | share links exist only for public posts | Non-public → hide share |
| Report post / comment / user | gate→login | ✓ | ✓ | `trust_safety.report` (rate limited, never paywalled) (SAFE-002) | Always on others' content |
| Follow | gate→login | **C** | **C** | Not blocked. Private accounts (`account_visibility=private`) → follow request (POST-006, PROF-004) | "Request to follow" label for private accounts |
| Negative feedback (hide, not interested, see less) | — | ✓ | ✓ | FEED-007 | Post menu |

### 5.2 Profiles

| Capability | Anon | Registered viewer | Backend policy | Web behaviour |
|---|---|---|---|---|
| View `/u/[handle]` | **C** | **C** | `profiles.get_public_profile(viewer, user)` returns `PublicProfile` (never `MyProfile` fields, PROF-005). `profile_visibility=connections` limits details to connections | Hidden fields are omitted, not blanked. Indexable only with the indexing consent requested in §10 |
| View posts on a profile | **C** (public posts only) | **C** (per post visibility; private account → followers only) | `social.can_view` per post (POST-008) | |
| View blocked / blocking user's profile | ✗ | ✗ | `trust_safety.is_blocked` (either direction) | **404**, identical to a non-existent handle |
| Edit own profile, preferences, privacy | — | ✓ | owner only. Handle change once per 30 days (PROF-003) | `409 conflict` → field error |
| Block / unblock | — | ✓ | never paywalled | Profile, DM and post menus |

### 5.3 Discovery and connections (relationship × capability)

Discovery is opt-in, off by default, and needs separate consent (DISC-001). Both viewer and target must have an active, visible discovery session for the same destination (DISC-003). Invisible users neither appear nor browse (DISC-006 → `403 discovery_invisible`).

| Capability | none | request sent | request received | connected | declined (requester side) | blocked (either) | Backend policy | Web behaviour |
|---|---|---|---|---|---|---|---|---|
| Appear in / see discovery results | **C** | **C** | **C** | **C** | **C** (deprioritized, DISC-008) | ✗ | `discovery.discover_travelers`: opted in, same destination, visible, not blocked; rate limits 60 queries/h and 10 destination switches/day (DISC-009) | Area label only, never distance or coordinates (DISC-004) |
| Send connection request | **C** | ✗ (cancel instead) | ✗ (accept instead) | ✗ | ✗ during 30-day cooldown (CONN-006) | ✗ | `connections.request`: email verified, target's `connection_requests_from` ∈ `everyone` / `shared_context` / `nobody` (CONN-004 → `403 connection_requests_restricted`), 20/day and 5/h (CONN-005) | Button reflects state; `nobody` → hide |
| Cancel request | — | ✓ | — | — | — | — | `connections.cancel` | show |
| Accept / decline | — | — | ✓ | — | — | — | Requester sees `declined` (PRD Q-4) | Inbox `/companions/requests` |
| Remove connection | — | — | — | ✓ | — | — | Silent to the other party (CONN-008) | Profile menu |
| Start direct message | ✗ | ✗ | ✗ | ✓ | ✗ | ✗ | `messaging.can_send`: **connected only** (DM-001 → `403 connection_required`), email verified, not blocked | "Connect to message" CTA |

### 5.4 Private messaging (Phase 4 web)

| Capability | Conversation member | Non-member | Backend policy | Web behaviour |
|---|---|---|---|---|
| Read conversation and history | ✓ | ✗ | membership-scoped queries (T-AZ-01) | Non-member → **404** for `/messages/[id]` |
| Send text / image | **C** | ✗ | `messaging.can_send(principal, conversation, membership, relationship, block_state)`; rate limit 30/min (T-MSG-03) | Blocked or connection removed → composer replaced by an explanation |
| Edit (≤ 15 min) / delete own message for everyone | ✓ | ✗ | DM-010 | Own messages only |
| React, reply, mark read | ✓ | ✗ | Read receipts reciprocal and optional (`read_receipts_enabled`, DM-007) | Receipt ticks hidden if either side disabled them |
| Mute / block / report | ✓ | ✗ | never paywalled (DM-011, DM-012) | Conversation menu |
| Fetch attachment | ✓ | ✗ | `media.signed_url(viewer, asset)` per request; URL ≤ 5 min (T-MSG-04) | Never cached across users |

### 5.5 Groups (role × capability, Phase 5 web)

v1 groups are **private and invite-only** (GRP-004). Unlisted/public visibility and join requests (GRP-006) are modeled but behind flags, and the web hides them until the flags are on. Joining never requires a subscription (GRP-008).

| Capability | none | invited | member | moderator | admin | owner | Backend policy (`groups.can(principal, action, group, membership, group_entitlement)`) | Web behaviour |
|---|---|---|---|---|---|---|---|---|
| See the group | ✗ | ✓ (preview) | ✓ | ✓ | ✓ | ✓ | private by default | none → **404** |
| Accept / decline invitation, redeem invite link | — | ✓ | — | — | — | — | `invitation_invalid` (expired, revoked, max uses); capacity (GRP-012) | `/groups/invitations` |
| **Create group** | — | — | — | — | — | — | user's own `groups.create` + `groups.owned` quota + email verified | Free → **upsell** on `/groups/new`; cap reached → quota |
| Read and send in group chat | ✗ | ✗ | **C** | ✓ | ✓ | ✓ | membership `active` (restricted members read only, GCHAT-004); admins-only chat mode (GCHAT-003) | Restricted → read-only banner |
| View members | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | profiles filtered by blocks | |
| DM another member | ✗ | ✗ | **C** | **C** | **C** | **C** | **Same rule as §5.3: connected only.** Shared membership grants nothing (GCHAT-005, T-AZ-04) | "Request private chat" sends a connection request (brief §19) |
| Create invitations (direct or link) | ✗ | ✗ | ✗ | **C** (if role has `invite`) | ✓ | ✓ | role permission **and** group premium active or in grace (07 §5) | Lapsed → owner/admins see disable+why with the grace date |
| Approve join requests (flagged) | ✗ | ✗ | ✗ | **C** | ✓ | ✓ | role + group premium | |
| Remove messages, restrict or remove members, handle reports | ✗ | ✗ | ✗ | ✓ (below own rank) | ✓ (below own rank) | ✓ | role rank rule (T-GRP-05); **never paywalled** | |
| Assign / revoke moderators | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ | role permission; not gated by premium (07 §5) | |
| Assign admins | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | rank rule | |
| Pin messages, post announcements | ✗ | ✗ | ✗ | ✓ | ✓ | ✓ | role permission; not gated (07 §5) | |
| Edit group details | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ | role permission; `If-Match` | |
| Increase capacity | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ | role + group premium; ≤ `group_max_capacity` (50) | |
| Transfer ownership | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | **always allowed**; recipient need not be premium (07 §5, GRP-010) | |
| Archive group | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | never silently deleted (GRP-011) | |
| Leave group | — | — | ✓ | ✓ | ✓ | **C** (transfer or archive first) | never paywalled | |
| Report group / member / message | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ | never paywalled | |

### 5.6 Challenges and riddles (Phase 7 web)

| Capability | member | moderator / admin with `challenges.manage` | Backend policy (`challenges.*`) | Web behaviour |
|---|---|---|---|---|
| View active / upcoming / completed | ✓ | ✓ | membership. Answers never reach member schemas (CHAL-008, T-CHAL-01) | |
| Create / edit draft / publish | ✗ | **C** | creator holds `challenges.create` **and** group premium active **and** ≤ 3 active challenges (07 §3.3). Prize types limited to CHAL-012; CHAL-013 types rejected. Real-world rewards need platform review before publishing (CHAL-014) | upsell (creator) or disable+why (group lapsed) |
| Request hint | ✓ | ✓ | hint schedule; `challenge_not_active` | disable+why before unlock |
| Submit answer | **C** | ✗ for the challenge's author | individual mode: the participant; team mode: **captain only** (CHAL-004); attempts and cooldown (CHAL-005); auditable server timestamps | Attempts left come from the server |
| Join a team / team thread | ✓ | ✓ | team mode only | |
| Judge (manual or AI-assisted) | ✗ | **C** | AI never final for non-badge rewards (CHAL-007); audited | |
| Publish results | ✗ | **C** | deterministic first-correct ordering (CHAL-009, T-CHAL-07) | |
| Open dispute | ✓ | ✓ | never paywalled; escalates to platform (CHAL-016) | |
| Fulfil real-world reward | ✗ | ✗ | platform `REWARDS_REVIEW` only | |

### 5.7 AI assistant, trips, guides, offline, membership

| Capability | Anon | Free | Prem | Backend policy | Web behaviour |
|---|---|---|---|---|---|
| AI demo on the homepage | ✓ (static, labelled example; no live generation) | ✓ | ✓ | none | "Example itinerary" label |
| Generate itinerary | gate→login | **C** (5/month) | **C** (60/month) | `ai_assistant.generate_itinerary`: `ai.itinerary_generations` quota (only succeeded generations count); global breaker → `503 ai_unavailable` | quota |
| Replan existing trip | — | ✗ | **C** (60/month) | `ai.trip_replan` + `ai.trip_replans` quota (AI-005) | upsell (free) |
| Conversational assistant | gate→login | **C** | **C** | AI-006 is "Could". Quota policy is undefined in doc 07 (§10) | Hidden behind a flag until defined |
| Save itinerary to a trip | — | ✓ | ✓ | trip owner or editor (TRIP-002) | |
| Create / edit / delete own trip | gate→login | ✓ | ✓ | `trips.*`; `If-Match` version | |
| Share trip with collaborators (editor/viewer) or a group | — | ✓ | ✓ | invitee blocks and settings (TRIP-005); trip `visibility` ∈ private / connections / group / public; private by default (T-LOC-08) | |
| View a shared trip | — | **C** | **C** | collaborator, group member, or visibility allows | Otherwise 404 |
| Browse guide library and free tours | ✓ (descriptions) | ✓ | ✓ | `guides.list_guides` | |
| Open premium guide | gate→login | **C** (`content:guide:<id>`) | ✓ | `guides.premium` or content grant (GUIDE-004) | Lock + upsell / buy |
| Play premium audio tour | gate→login | **C** (`content:audio_tour:<id>`) | ✓ | `audio_tours.premium` or content grant | Lock + upsell / buy |
| Download offline package (PWA) | ✗ | **C** (1 active) | **C** (15 active) | `offline.packages` quota; signed manifest; licence expiry (OFF-005) | Browser capability check first; quota |
| View pricing | ✓ | ✓ | ✓ | `GET /v1/billing/products?platform=web` | Web purchase hidden if a store subscription already grants `premium` (07 §2, ADR-0012) |
| Start checkout | gate→login | ✓ | **C** (plan change only) | Stripe Checkout Session (07 §6) | Until the adapter exists: disabled with "Not yet available on web" |
| Manage subscription | — | — | ✓ | Stripe Portal for web purchases; store link for store purchases | |

### 5.8 Account, privacy and data rights (never paywalled)

| Capability | Owner | Anyone else | Backend policy | Web behaviour |
|---|---|---|---|---|
| List / revoke own sessions | ✓ | ✗ | AUTH-006 | `/settings/sessions` (shows web sessions as `platform=web`) |
| Privacy settings (discovery, granularity, request policy, profile/account visibility, read receipts, post location default, trips on profile) | ✓ | ✗ | PROF-007; defaults per ERD (discovery **off**) | `/settings/privacy` |
| Withdraw discovery or location consent | ✓ | ✗ | instant effect (doc 08 §5.1) | One toggle, no confirmation wall |
| Export my data | ✓ | ✗ | AUTH-011 (async archive, link valid 7 days) | `/settings/data` |
| Delete my account | ✓ (recent re-authentication) | ✗ | AUTH-010: 30-day reversible grace | Typed-phrase confirmation; login during grace offers cancel |
| Consent management (analytics, marketing) | ✓ | ✗ | `consent_records` (AUTH-009) | Cookie banner + `/settings/privacy` |

## 6. Account status effects

| Status / state | Sign in | Read | Write social content | Message | Web |
|---|---|---|---|---|---|
| `active`, verified | ✓ | ✓ | ✓ | ✓ (connections) | — |
| `active`, email unverified | ✓ | ✓ | ✗ (`email_unverified`) | ✗ | Persistent "Verify your email" banner with resend |
| `active` + moderation restriction | ✓ | ✓ | ✗ (per restriction) | per restriction | Banner with the restriction and its end date |
| `suspended` | ✗ (`account_suspended`) | ✗ | ✗ | ✗ | Login error page with appeal path |
| `deactivated` (self) | ✓ (reactivates) | — | — | — | Content hidden while deactivated |
| `pending_deletion` | ✓ (can cancel during grace) | own data | ✗ | ✗ | Cancel-deletion screen |
| `deleted` | ✗ | — | — | — | Generic login failure (no enumeration, T-AUTH-04) |

## 7. Route-area gates in the web (defence in depth)

| Area | `proxy.ts` | Layout (server) | Backend |
|---|---|---|---|
| Public `/`, `/destinations/**`, `/stories/**`, `/pricing`, legal | Locale only. Signed-in visitor on `/` → `/feed` | No cookie access (keeps pages cacheable) | Public read endpoints |
| `(auth)` `/login`, `/register`, … | Signed-in → `/feed` | — | IdP + `/v1/auth/*` |
| `/onboarding` | Requires `tb_session` | `GET /v1/users/me`; already onboarded → `/feed` | `profiles.*` |
| `(traveler)` | Requires `tb_session`, else `/login?next=` | `GET /v1/users/me` (embeds `entitlements`; `GET /v1/billing/entitlements` refreshes them after purchases); not onboarded → `/onboarding`; `suspended` → sign-out | Per-endpoint policies |
| `/admin/**` | Requires `tb_session`; `ADMIN_ALLOWED_HOSTS` check if set | `roles ∩ platform roles ≠ ∅`, else **404**; per-section permission, else **404** | `require_platform_permission` |
| `/dev/login`, `POST /api/auth/dev` | — | 404 unless `DevIdentityProvider` is active (`APP_ENV ∈ {development, test}`) | Dev IdP only (T-AUTH-08) |

## 8. Sensitive administrative actions

| Action | Extra controls |
|---|---|
| Reveal sensitive user data (`USERS_READ_SENSITIVE`) | Mandatory justification (ADM-003). Field-level reveal ("Show email") instead of default display. Audited with the justification |
| Suspend / ban user, suspend group | Reason code + note. User notified with an appeal path. Audited |
| Remove content | Reason code from the community-guidelines taxonomy. The author sees the reason. Appealable |
| Read message content | Only the evidence snapshot attached to a report (T-AZ-07). No general message browsing |
| Grant a platform role (`ROLES_ASSIGN`) | Superadmin only. **Two-person rule** (a second superadmin approves). Cannot grant to self. Audited |
| Change entitlement mappings / quotas (`BILLING_CONFIGURE`) | Superadmin only. Change preview. Audited. Takes effect through `EntitlementGranted/Revoked` events |
| Promotional grant (`PROMO_GRANT`) | Expiry required. Audited (BILL-009) |
| Execute account deletion | Only after the AUTH-010 grace period. Irreversible-action confirmation |

## 9. Test obligations

Every ✗ or **C** row in §5 has at least one negative backend test (owned by the backend module, doc 10 §3.4), and, where the web renders a distinct state, a web test asserting the behaviour code (hide / disable+why / upsell / quota / verify-email / 404). The web's cross-cutting authorization tests are in [08 §12](08-security-privacy.md#12-authorization-test-catalogue) and [10 §8](10-test-strategy.md#8-security-tests).

## 10. Open questions / requests to the backend stream

1. **Indexing consent for public profiles.** Brief §26 needs a per-user opt-in before a profile page is indexable. The ERD has `account_visibility` and `profile_visibility` but no indexing flag. Request: add `user_privacy_settings.search_indexing_enabled` (default `false`). Until then, `/u/[handle]` is always `noindex`.
2. **Platform `Permission` enum.** The permission names in §4 are a web proposal derived from ADM-001…006. Request: publish the backend enum (doc 02 §9) so admin navigation can mirror it 1:1.
3. **AI chat quota.** AI-006 (conversational assistant) has no quota in doc 07. Request a quota key (for example `ai.chat_messages`) before the web enables `/assistant` chat.
4. **`support` and sensitive data.** Whether `support` may reveal emails needs a privacy-officer decision. §4 assumes yes, with justification.
5. **Account restriction representation.** The ERD models `restrict` as a moderation action, not a `users.status` value. Request: expose active restrictions on `GET /v1/users/me` (`restrictions: { kind, ends_at }[]`) so the web can show the banner in §6.
