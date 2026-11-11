# 01 — Product Requirements Document (PRD)

| | |
|---|---|
| **Product** | Travel Buddy (working name): global AI travel guide and social travel community |
| **Version** | 1.0 (Phase 0 baseline) |
| **Status** | Draft for approval |
| **Platforms** | iOS, Android (React Native), web administration console |
| **Source** | Master Development Prompt v1.0 |

## Version history

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-11-09 | Initial PRD derived from Master Development Prompt v1.0. Requirement IDs established. |
| 1.4 | 2026-11-09 | Q-1 resolved: Supabase Auth is the identity provider (ADR-0020). No requirement changes. |
| 1.3 | 2026-11-09 | Q-8 partially resolved: Supabase chosen as the managed PostgreSQL provider (ADR-0018). No requirement changes. |
| 1.2 | 2026-11-09 | Added PROF-008 (opt-in search-engine indexing), NOTIF-005 (Web Push), ADM-007..009 (staff MFA, staff session timeouts, audit justification), SAFE-012 (web cache purge on visibility loss) and SAFE-013 (own-account restrictions shown to the user). Requested by the web workstream. All additive. |
| 1.1 | 2026-11-09 | Added DEST-006 (public destination directory and sitemap enumeration), DEST-007 (editorial media attribution and verified rights) and GUIDE-006 (anonymous free guides, structured FAQ). Requested by the web workstream for the public SEO site. All additive. |

## How to read this document

* Every requirement has a stable ID `AREA-NNN`. IDs are **never reused or renumbered**. Superseded requirements are marked ~~struck~~ with a pointer to their replacement.
* **Priority:** **M** = Must for its phase · **S** = Should · **C** = Could.
* **Phase** refers to [09 — Backlog](09-development-backlog.md).
* Tests reference requirement IDs with `@pytest.mark.req("AREA-NNN")` (backend) or `/* req: AREA-NNN */` (mobile). `scripts/trace_requirements.py` produces the traceability matrix.

---

## 1. Vision and goals

**Vision.** An intelligent travel companion that helps people discover destinations, plan trips, meet like-minded travelers on their own terms, and explore the world. It covers the trip before, during and after.

**Positioning.** It combines AI itinerary planning (Wanderlog-class), GPS audio guides with offline packs (GuideAlong-class) and traveler social discovery (Roamy-class). The differentiator is the **destination-centric social layer** (content keyed to *where it happened*, not who posted it) plus **premium travel groups with interactive challenges**.

### 1.1 Product goals (first 12 months after launch)

| ID | Goal | Measure |
|---|---|---|
| G-1 | New users find the app useful immediately | ≥ 90 % of new accounts see ≥ 10 relevant posts in their first session. D1 retention ≥ 35 % |
| G-2 | The guide is useful without any social participation | ≥ 30 % of WAU use trips, guides or AI without ever enabling discovery |
| G-3 | Safe companion discovery | Reports per 1,000 connection requests ≤ 5. Median moderation response for priority reports < 2 h |
| G-4 | Sustainable revenue | Free → premium conversion ≥ 3 % of MAU. Premium monthly churn ≤ 8 % |
| G-5 | Global readiness | 5 launch languages. Adding a language requires zero schema or code changes |

### 1.2 Non-goals for v1

* Booking or reselling flights, hotels or tickets (future partner integrations only).
* Building a turn-by-turn navigation engine. Mapping and routing are integrated from providers.
* End-to-end encrypted messaging (it needs its own threat model and key management spec first).
* Paid-entry contests, raffles, wagers or cash prizes.
* Real-time location sharing or movement trails.
* Public group discovery (private invite-only groups first).

## 2. Personas

| Persona | Description | Primary needs |
|---|---|---|
| **Sofia, solo backpacker** (26, Spain) | Long trips on a budget, open to meeting people | Local tips, companions with overlapping dates, safety controls |
| **James, city-break planner** (38, UK) | Short trips, time-poor, plans ahead | Fast AI itinerary, offline guide, *no* social exposure |
| **Ana, group organizer** (31, Brazil) | Organizes trips for friends and online communities | Private groups, chat, activities that engage members; will pay for this |
| **Kenji, digital nomad** (29, Japan) | Lives in a city for 1–3 months | Neighborhood-level content, meeting nomads, long-running groups |
| **Moderator Priya** (internal) | Trust and safety staff | Prioritized queue, evidence, fast enforcement, audit trail |

## 3. User roles and access matrix

| Capability | Guest | Free | Premium | Group admin* | Platform admin |
|---|---|---|---|---|---|
| Browse public destinations, limited public posts | ✓ | ✓ | ✓ | ✓ | ✓ |
| Profile, feed, publish posts and comments, follow | — | ✓ | ✓ | ✓ | ✓ |
| Basic AI itinerary (monthly quota) | — | ✓ | ✓ (higher) | ✓ | — |
| Traveler discovery (opt-in), connection requests | — | ✓ | ✓ | ✓ | — |
| Direct messages with connections | — | ✓ | ✓ | ✓ | — |
| Join groups (invited or approved), group chat, challenges | — | ✓ | ✓ | ✓ | — |
| **Create travel groups** | — | — | ✓ | — | — |
| Invite and manage members, assign moderators, configure privacy | — | — | — | ✓ | — |
| **Create challenges and riddles, define prizes, validate winners** | — | — | — | ✓ (owner premium) | — |
| Premium guides, audio tours, expanded offline allowance | — | — | ✓ | — | — |
| Moderate content and users, manage destinations and subscriptions config | — | — | — | — | ✓ (RBAC) |

\*Group admin is a **resource-scoped** role (owner, admin, moderator), not an account type. Premium capabilities of a group derive from the **owner's** entitlement ([07](07-subscription-entitlement-policy.md)). Safety moderation inside a group is never paywalled.

---

## 4. Functional requirements

### 4.1 Identity and onboarding: AUTH

| ID | Requirement | Pri | Phase | Acceptance criteria |
|---|---|---|---|---|
| AUTH-001 | Users register with email and password through a managed OIDC IdP. The platform never stores passwords | M | 1 | No password column exists. Registration completes only after IdP token verification |
| AUTH-002 | Sign in with Apple | M | 1 | Apple sign-in yields a platform session. Apple private-relay email is accepted |
| AUTH-003 | Google Sign-In | M | 1 | As AUTH-002 |
| AUTH-004 | Email verification is required before publishing, messaging or connection requests | M | 1 | Unverified users get `403 email_unverified` on those mutations and can still browse |
| AUTH-005 | Password reset (email method) via the IdP | M | 1 | Reset flow reachable from login. Existing platform sessions are revoked on password change (IdP event or next login) |
| AUTH-006 | Multi-device sessions: list and revoke devices | M | 1 | `GET /v1/users/me/sessions` lists devices. Revoking one ends its refresh capability and its WebSocket within 60 s |
| AUTH-007 | Refresh-token rotation with reuse detection | M | 1 | Reusing a rotated refresh token revokes the entire session family and is audited |
| AUTH-008 | Minimum age gate: **18+ at launch** (pending legal review per market). DOB is used transiently and only `birth_year` is stored | M | 1 | Under-18 DOB → registration rejected with `age_restricted`, no account created |
| AUTH-009 | Terms and privacy consent captured with version | M | 1 | `consent_records` row per accepted document version |
| AUTH-010 | Account deletion: self-service with a 30-day reversible grace period, then irreversible | M | 1 | Deletion saga completes within 30 days + 7. Login during grace cancels deletion |
| AUTH-011 | Data export (GDPR Art. 15/20) delivered as a downloadable archive | S | 6 | Export ready ≤ 72 h, link valid 7 days |
| AUTH-012 | Guest mode: browse limited public destination content without an account | S | 1 | Unauthenticated `GET /v1/destinations/*` and capped public feed (20 posts) |

### 4.2 Profiles and preferences: PROF

| ID | Requirement | Pri | Phase | Acceptance criteria |
|---|---|---|---|---|
| PROF-001 | Onboarding collects display name (required), photo (optional), preferred language, home country (optional), interests, travel styles, current/upcoming destinations, bio (optional), location permission choice, discovery visibility choice | M | 1 | Only display name and language are required. Every optional step is skippable |
| PROF-002 | After onboarding the user lands **directly on the discovery feed** | M | 1 | E2E: registration → feed with ≥ 1 post (seeded launch destinations) |
| PROF-003 | Unique handle for mentions and invitations | M | 1 | Case-insensitive uniqueness. Handle change allowed once per 30 days |
| PROF-004 | Public vs private account | M | 1 | Private: follow requires approval and posts are visible to followers only |
| PROF-005 | Public profile view hides email, birth data, sessions, coordinates and exact location | M | 1 | `PublicProfile` schema contains none of those fields (contract test) |
| PROF-006 | Preferences: UI language, content languages, time zone, currency, distance unit, notification matrix | M | 1 | Changing UI language re-renders without restart |
| PROF-008 | Search-engine indexing of a user's public profile and public posts is **opt-in** (default off), recorded as consent. Without it, pages are `noindex` and excluded from sitemaps | M | 1 | New account → `indexable: false` everywhere. Opting out triggers cache revalidation (SAFE-012) |
| PROF-007 | Privacy settings center (discovery, connection-request policy, profile visibility, read receipts, default post location precision) | M | 1–2 | All settings persist server-side and apply immediately |

### 4.3 Location intelligence: LOC

| ID | Requirement | Pri | Phase | Acceptance criteria |
|---|---|---|---|---|
| LOC-001 | Six location concepts are modeled separately: home, current device, selected browse destination, post destination, trip destination, traveler discovery location | M | 1 | Each concept has its own storage and lifecycle (ERD §4). No shared "user location" column |
| LOC-002 | Browse any destination regardless of physical location (London user browsing Rio) | M | 1 | `PUT /v1/users/me/browse-destination` + feed by `destination_id`, with no GPS needed |
| LOC-003 | Device GPS is used only with OS permission and is never persisted. It is rounded to ~110 m before server use and redacted from logs | M | 1 | Grep and log tests confirm no coordinate persistence. Log redaction test |
| LOC-004 | IP address is **never** used to place anyone silently. It may only suggest a starting point on the Companions map, shown as approximate, looked up locally and never stored; becoming discoverable still takes the traveller's own action (amended 2026-11-11, ADR-0030) | M | 1 | No GeoIP dependency in feed or discovery modules (the lookup lives in the location module). Test: the lookup alone starts no discovery session |
| LOC-005 | Point → destination resolution (neighborhood, city, country) with PostGIS | M | 1 | Copacabana point resolves to Copacabana → Rio de Janeiro → RJ → Brazil |
| LOC-006 | Destination hierarchy with country, region, city and neighborhood filters | M | 1 | Feed filters at each level return content from descendants |
| LOC-007 | Location freshness: a device location older than 15 min is not used for "Nearby". The client must re-acquire | S | 1 | Server rejects `near` with `near_ts` older than 15 min (`stale_location`) |
| LOC-008 | Coordinate accuracy metadata accepted (`near_accuracy_m`). Readings with accuracy > 5 km are treated as city-level only | S | 1 | Unit test of resolution precision downgrade |
| LOC-009 | **No discovery API ever returns another user's coordinates or distance** | M | 2 | Contract test plus security test T-LOC-01 |
| LOC-010 | The Companions map starts around the city the IP address points to: a local DB-IP Lite lookup, rounded to about 1 km, city level only, never stored or logged, labelled approximate and credited. The traveller can choose another city | S | 2 | `GET /v1/users/me/approximate-location`; unit and integration tests; unknown addresses get `422 location_unresolvable` and the app asks for a city |

### 4.4 Destination catalog: DEST

| ID | Requirement | Pri | Phase | Acceptance criteria |
|---|---|---|---|---|
| DEST-001 | Destination search across localized names (accent- and case-insensitive, typo-tolerant) | M | 1 | "rio de janero" → Rio de Janeiro in top 3. p95 < 150 ms |
| DEST-002 | Localized destination names per UI locale with fallback | M | 1 | `Accept-Language: de` returns "Rio de Janeiro"; `Lisbon` / `Lisboa` per locale |
| DEST-003 | Places (attractions, restaurants …) with licensed data, attribution and freshness | M | 4 | Every place shows source attribution. Provider data older than threshold is flagged |
| DEST-004 | Featured destinations and editorial content managed by admins | S | 1 | Admin can feature and unfeature. Change is audited |
| DEST-006 | Public destination directory: anonymous, cursor-paginated listing of active destinations, filterable by kind, country, continent and featured, with a stable sort for complete sitemap enumeration. Directory cards show localized country name, continent, tagline and cover | M | 1 | `GET /v1/destinations?sort=slug` enumerates every active destination exactly once across pages while the catalog changes |
| DEST-007 | Editorial and licensed media (destination covers, guide and audio imagery) carries attribution (credit, license, source URL) that clients display. Rights are verified before publication | M | 1 | An editorial asset without `rights_verified_at` cannot be attached to a published destination or guide. `MediaRef.attribution` is present for editorial media |
| DEST-005 | Launch destination set seeded with boundaries (initial: 10 cities incl. Rio de Janeiro, Lisbon, Barcelona, Mexico City, Paris, Berlin, London, New York, Buenos Aires, Bangkok) | M | 1 | Boundaries loaded from OSM/geoBoundaries with license recorded |

### 4.5 Social posts and engagement: POST

| ID | Requirement | Pri | Phase | Acceptance criteria |
|---|---|---|---|---|
| POST-001 | Publish text, photo, short video, story, attraction/restaurant recommendation, review, tip, itinerary summary, experience | M | 1 (video S) | Each kind validates its required fields. Review requires rating 1–5 |
| POST-002 | Post carries destination metadata. The author chooses the precision: none / destination / public place | M | 1 | Default from privacy settings. `none` posts don't appear in destination feeds |
| POST-003 | Location relevance derives **from post destination metadata only**, never from author nationality, residence or IP | M | 1 | UK-resident author's Rio post appears in Rio feed. Author's home is never a ranking input |
| POST-004 | Image/video metadata (EXIF, GPS) stripped before publication | M | 1 | Uploaded JPEG with GPS EXIF → served variants contain no EXIF (integration test) |
| POST-005 | Reactions (like, love, helpful, wow; one per user, changeable), comments (one reply level), bookmarks, shares (external share sheet with tracked count) | M | 1 | Counters consistent under concurrency (reconciliation job) |
| POST-006 | Follow and unfollow. Follow requests for private accounts | M | 1 | — |
| POST-007 | Edit (marks `edited`) and delete (tombstone, hard delete after 30 days) | M | 1 | Edited posts show the indicator. Deleted posts disappear from all feeds within 60 s |
| POST-008 | Visibility: public, followers, connections, private | M | 1 | Visibility enforced in feed queries and direct GET (404 when not visible) |
| POST-009 | Tags and categories, max 10 tags | S | 1 | — |
| POST-010 | Optional machine translation of posts, clearly labelled as machine-translated, original always available | S | 4 | Translation never overwrites the original. UI shows "Translated from Portuguese · Show original" |
| POST-011 | Content language detected or declared, filterable | M | 1 | — |

### 4.6 Feed and ranking: FEED

| ID | Requirement | Pri | Phase | Acceptance criteria |
|---|---|---|---|---|
| FEED-001 | A new user never sees an empty feed. Source order: (1) GPS-resolved destination if permitted, (2) selected destination, (3) upcoming destinations, (4) interests, (5) global popular | M | 1 | E2E with no follows, no permission → non-empty feed from selected or popular |
| FEED-002 | Tabs: **For You**, **Nearby** (destination-tagged content near the device), **Following**, **Destinations** (chosen destinations) | M | 1 | "Nearby" content never includes people. Discovery lives in Companions |
| FEED-003 | Filters: current location, city, country, neighborhood, radius (Nearby), recent/popular, following, categories, content language, saved destinations | M | 1 | Each filter has an API parameter and an integration test |
| FEED-004 | Cursor pagination with stable pages (snapshot) | M | 1 | No duplicates across 10 consecutive pages while new posts arrive |
| FEED-005 | Blocked users' content excluded in both directions. Removed/limited content excluded | M | 1 | Security test |
| FEED-006 | Author diversity: max 2 posts per author per page. Near-duplicate suppression | M | 1 | Unit test on the ranker |
| FEED-007 | Negative feedback (hide, not interested, see less from author) affects ranking | S | 1 | Hidden post never reappears. Author penalty applied |
| FEED-020 | Deterministic ranking with documented, versioned weights: geographic relevance, destination match, recency (half-life), interest overlap, engagement quality (helpful-weighted, per-view-normalized), author trust, content quality, language match, negative feedback | M | 1 | Ranker is a pure function. Weights are in config with a version recorded per feed session |
| FEED-021 | ML ranking only after sufficient interaction data, behind a flag, A/B tested against the deterministic baseline | C | 7 | — |
| FEED-022 | Redis-cached feed sessions. p95 feed latency < 300 ms server-side | M | 1 | Load test target |

**Initial ranking formula (FEED-020)**, v1 weights, all features normalized to [0, 1]:

```
score = 0.30·destination_match + 0.20·recency + 0.15·interest_overlap
      + 0.12·engagement_quality + 0.08·content_quality + 0.07·author_trust
      + 0.05·language_match + 0.03·geo_proximity
      − 0.40·negative_feedback − 0.25·report_signal
recency = 0.5 ^ (age_hours / 72)
destination_match = 1.0 exact, 0.8 child (neighborhood within city), 0.5 parent, 0.2 same country
```

### 4.7 Traveler discovery: DISC

| ID | Requirement | Pri | Phase | Acceptance criteria |
|---|---|---|---|---|
| DISC-001 | Discovery is **opt-in and off by default**, with separate explicit consent | M | 2 | New account: `discovery_enabled=false`. Enabling requires the consent screen and a recorded consent |
| DISC-002 | Discovery sessions are temporary (default 24 h, max 72 h) and expire automatically | M | 2 | Expired sessions are invisible within 1 min (query filter, no job dependency) |
| DISC-003 | Users appear only in **destination-scoped** discovery (city, or neighborhood if chosen), never because devices are physically close | M | 2 | No coordinate-based people query exists |
| DISC-004 | Results show area label (city / neighborhood) only. **No distances and no coordinates** | M | 2 | Contract test |
| DISC-005 | Filters and matching: interests, travel-date overlap, languages, travel styles | M | 2 | Match score uses documented weights. Shared interests shown as chips |
| DISC-006 | Invisible mode: neither appears nor browses | M | 2 | Invisible users get `403 discovery_invisible` on the discover endpoint |
| DISC-007 | Profile preview respects profile visibility settings | M | 2 | — |
| DISC-008 | Blocked users never appear (both directions). Recently declined requesters are deprioritized | M | 2 | Security test |
| DISC-009 | Anti-enumeration: rate limits on discovery queries (60/h) and destination switches (10/day) | M | 2 | Security test T-LOC-03 |
| DISC-010 | Safety guidance shown before first enablement and in profile previews ("meet in public places …"). Discovery is never described as safe | M | 2 | Copy reviewed by trust and safety. Shown on first enable |
| DISC-011 | The full travel guide works without ever enabling discovery | M | 2 | E2E: complete trip planning and guide download with discovery off |
| DISC-012 | Discovery results can be shown on a map. Each traveller is drawn around the public centre of the area they share (city or neighbourhood), never at a position of their own, and the map says so. Tapping a traveller opens their profile, and the results are also listed for screen readers | S | 2 | Pin layout tests; discover contract unchanged (no coordinates); app test that only travellers on the map can be opened |

### 4.8 Connections: CONN

| ID | Requirement | Pri | Phase | Acceptance criteria |
|---|---|---|---|---|
| CONN-001 | Relationship states: none, request pending, request received, connected, declined, blocked | M | 2 | State machine unit tests cover every transition, with invalid transitions rejected |
| CONN-002 | A request never automatically creates a connection. Explicit accept required | M | 2 | — |
| CONN-003 | Pending-request inbox (incoming and outgoing), with accept, decline and cancel | M | 2 | — |
| CONN-004 | Recipient's `connection_requests_from` policy enforced (everyone / shared context / nobody) | M | 2 | `403 connection_requests_restricted` |
| CONN-005 | Rate limits on unsolicited requests: 20/day and 5/hour per user. Stricter for new accounts (< 7 days: 5/day) | M | 2 | Security test |
| CONN-006 | Re-request cooldown after decline (30 days) | M | 2 | `409 connection_request_cooldown` |
| CONN-007 | Requests expire after 30 days | S | 2 | — |
| CONN-008 | Remove connection (silent to the other party) | M | 2 | — |
| CONN-009 | Blocking immediately ends the connection, pending requests, follows and DM send rights, and hides each from the other's discovery and feeds | M | 2 | Integration test: all effects in one transaction |

### 4.9 Direct messaging: DM

| ID | Requirement | Pri | Phase | Acceptance criteria |
|---|---|---|---|---|
| DM-001 | One-to-one conversations between **connected** users only (v1 trust relationship) | M | 3 | `403 connection_required` otherwise |
| DM-002 | Text and image messages. Images scanned and served through signed URLs | M | 3 | — |
| DM-003 | Real-time delivery over authenticated WebSocket. REST send equivalent | M | 3 | Same service path for both (integration test) |
| DM-004 | Durable storage **before** fanout. WebSocket is never the source of truth | M | 3 | Kill realtime node mid-send → message is in history after reconnect |
| DM-005 | Idempotent submission via client-generated `client_message_id` | M | 3 | Duplicate send → same message ID, no duplicate row |
| DM-006 | Delivery acknowledgements, per-conversation sequence, missed-message sync on reconnect | M | 3 | Gap detection test |
| DM-007 | Read receipts, reciprocal and configurable | M | 3 | Disabled → neither sends nor sees read state |
| DM-008 | Typing indicators (ephemeral) | S | 3 | — |
| DM-009 | Push notifications for offline recipients, respecting mute and notification level | M | 3 | No message body in push payload when the user has disabled previews |
| DM-010 | Edit within 15 min (marks edited). Delete for everyone (tombstone) | M | 3 | — |
| DM-011 | Mute conversation. History pagination | M | 3 | — |
| DM-012 | Block and report from the conversation. Blocking stops delivery both ways immediately | M | 3 | — |
| DM-013 | Messages are not end-to-end encrypted in v1. The privacy policy states this. Encryption in transit (TLS 1.2+) and at rest | M | 3 | — |

### 4.10 Travel groups: GRP

| ID | Requirement | Pri | Phase | Acceptance criteria |
|---|---|---|---|---|
| GRP-001 | Only users with an active premium entitlement can create groups, validated on the backend | M | 3 | Free user → `403 entitlement_required` (problem+json with `entitlement: groups.create`) |
| GRP-002 | Creator becomes owner and initial administrator | M | 3 | — |
| GRP-003 | Group properties: name, description, cover, destination or itinerary, dates, privacy, capacity, roles, policies | M | 3 | — |
| GRP-004 | v1 visibility: **private, invite-only**. Unlisted and public are modeled but behind flags | M | 3 | — |
| GRP-005 | Direct invitations to registered users and expiring invitation links (max uses, revocable) | M | 3 | Token stored hashed. Reuse beyond `max_uses` rejected under concurrency |
| GRP-006 | Join requests reviewed by admins (for `request_to_join` groups, behind a flag) | S | 3 | — |
| GRP-007 | Roles: owner, admin, moderator, member, with explicit permission sets | M | 3 | Authorization matrix test per role × action |
| GRP-008 | Joining a group does not require a subscription | M | 3 | Free user can accept an invitation |
| GRP-009 | Owner's subscription lapse: data and memberships preserved, no new group creation, premium admin tools restricted after the configurable grace period, safety moderation always available | M | 3 | Policy tests ([07](07-subscription-entitlement-policy.md) §5) |
| GRP-010 | Ownership transfer (offer → accept) | M | 3 | Audited |
| GRP-011 | Group data is never silently deleted. Archival only, by owner action or policy, with notice | M | 3 | — |
| GRP-012 | Capacity enforced transactionally | M | 3 | Concurrent joins never exceed capacity |
| GRP-013 | Owned-group cap per premium user (default 10) | S | 3 | — |

### 4.11 Group communication: GCHAT

| ID | Requirement | Pri | Phase | Acceptance criteria |
|---|---|---|---|---|
| GCHAT-001 | Every group has one shared chat room | M | 3 | Created with the group |
| GCHAT-002 | Text, photos, reactions, reply threads, pinned messages, mentions, mute | M | 3 | — |
| GCHAT-003 | Administrator announcements (highlighted, notify all, optionally admins-only chat mode) | M | 3 | — |
| GCHAT-004 | Moderation: remove messages, temporarily restrict members, remove members, manage moderators | M | 3 | Restricted members can read but not send. Audited |
| GCHAT-005 | Group membership does **not** grant unsolicited DMs. DMs still require a connection | M | 3 | Security test |
| GCHAT-006 | New-member history visibility configurable (full / from join) | S | 3 | — |
| GCHAT-007 | Removed members lose access to group chat immediately, including the realtime subscription | M | 3 | Security test: cross-group leakage |

### 4.12 Challenges and prizes: CHAL

| ID | Requirement | Pri | Phase | Acceptance criteria |
|---|---|---|---|---|
| CHAL-001 | Group admins of groups with active premium features can create riddle challenges | M | 5 | — |
| CHAL-002 | Fields: title, riddle text, media, validation method, hints, start/end, max attempts, prize description, winner policy, rules, status | M | 5 | Server validation of config (start < end, attempts 1–20, rewards allowed) |
| CHAL-003 | Lifecycle draft → scheduled → active → judging → completed (or cancelled). Activation at start time by the scheduler, with members notified | M | 5 | — |
| CHAL-004 | Individual and team solving modes. Team has a shared thread and a single authorized submitter (captain) | M | 5 | Non-captain team submission rejected |
| CHAL-005 | Brute-force resistance: max attempts, cooldown between attempts, rate limit, no answer feedback beyond correct/incorrect | M | 5 | Security test |
| CHAL-006 | Answer validation: normalized exact match, multiple accepted answers, admin review, AI-assisted semantic evaluation | M | 5 | Normalization unit tests (case, accents, punctuation, whitespace, articles) |
| CHAL-007 | AI is never the sole authority for real-world rewards. AI results for non-badge rewards are `needs_review` until an admin confirms | M | 5 | Policy test |
| CHAL-008 | Hidden answers and judging criteria never reach unauthorized clients | M | 5 | Contract test: member schemas contain no answer fields. Answers endpoint requires `challenges.judge` and is audited |
| CHAL-009 | Submissions recorded transactionally and auditable. First-correct ordering is deterministic | M | 5 | Concurrency test |
| CHAL-010 | Winner policies: first correct, first N correct, all correct, admin selects | M | 5 | — |
| CHAL-011 | Results published to the group | M | 5 | — |
| CHAL-012 | Prize types: in-app badges, non-transferable achievements, sponsor discount codes, documented non-cash promotional rewards | M | 5 | — |
| CHAL-013 | **Prohibited:** paid entry, raffles and random draws, wagers, cash or cash-equivalent or transferable monetary rewards | M | 5 | Validation rejects them. Monetary-pattern descriptions routed to review |
| CHAL-014 | Real-world rewards require eligibility rules, a fulfillment owner, platform review and jurisdiction notice | M | 5 | Cannot publish until `review_status=approved` |
| CHAL-015 | Fulfillment state machine (pending → issued → delivered, failed, cancelled, disputed), fully audited | M | 5 | — |
| CHAL-016 | Disputes raised by participants, resolved by group admins, escalated to platform moderation | S | 5 | — |
| CHAL-017 | Activity framework extensible to trivia, scavenger hunts, photo challenges, quizzes, missions | S | 7 | `kind` discriminator + per-kind validator interface |

### 4.13 AI travel assistant: AI

| ID | Requirement | Pri | Phase | Acceptance criteria |
|---|---|---|---|---|
| AI-001 | Provider-independent orchestration (port + adapters), with the model selected per task by config | M | 4 | Swapping provider requires config only |
| AI-002 | Personalized itinerary generation returning **schema-validated structured data** (days, items, place refs, durations, constraints, attribution, confidence, freshness) | M | 4 | Invalid model output never reaches the client (validation and repair, then a typed error) |
| AI-003 | Activities reference catalog `place_id`s or are flagged `unverified` | M | 4 | — |
| AI-004 | Never invents opening hours, ticket availability, live transit, reservation availability or safety guarantees. Such data comes only from licensed sources with freshness | M | 4 | Output schema has no such fields. Red-team eval set |
| AI-005 | Context-sensitive replanning of an existing trip (weather, closures, user edits) | S | 4 | Premium feature `ai.trip_replan` |
| AI-006 | Conversational travel assistance | C | 4 | — |
| AI-007 | Multilingual output in the user's UI language | M | 4 | — |
| AI-008 | Data minimization: no exact locations, private messages or other users' data in prompts without a defined purpose and consent | M | 4 | Context builder accepts typed inputs only (code review + test) |
| AI-009 | Cost controls: per-user quotas by entitlement, global spend circuit breaker, per-call telemetry | M | 4 | — |
| AI-010 | Preference learning from explicit signals (saved places, edits, ratings), with a user-visible reset | C | 7 | — |

### 4.14 Trips and itineraries: TRIP

| ID | Requirement | Pri | Phase | Acceptance criteria |
|---|---|---|---|---|
| TRIP-001 | Create and edit trips, with days and items (activities, meals, transit, lodging, notes) | M | 4 | — |
| TRIP-002 | Save AI itineraries as editable trips | M | 4 | — |
| TRIP-003 | Saved places and collections | M | 4 | — |
| TRIP-004 | Trips fully available offline with conflict-safe sync (version + tombstones, last-writer-wins per item with conflict surfacing) | M | 4 | Offline edit → reconnect → merged |
| TRIP-005 | Share trip with collaborators (editor/viewer) or link to a group | S | 4 | — |
| TRIP-006 | Publish itinerary summary as a post | S | 4 | — |

### 4.15 Maps and guides: GUIDE

| ID | Requirement | Pri | Phase | Acceptance criteria |
|---|---|---|---|---|
| GUIDE-001 | Interactive map with places and itinerary overlay (integrated provider) | M | 4 | — |
| GUIDE-002 | Place details with attribution and freshness | M | 4 | — |
| GUIDE-003 | Walking route previews from a routing provider | M | 4 | — |
| GUIDE-004 | Destination guides (free and premium tiers) | M | 4 | Premium guide requires `guides.premium` or a content purchase |
| GUIDE-006 | Free-tier guides are readable without an account (server-rendered for SEO). FAQ content is structured (question and answer) so clients can emit FAQ structured data | S | 4 | Anonymous `GET /v1/guides/{id}`: free → 200, premium → 401. FAQ sections expose `faq_items` |
| GUIDE-005 | Audio tours with location-triggered stops (on-device geofencing; no location sent to the server) | M | 4 | — |

### 4.16 Offline: OFF

| ID | Requirement | Pri | Phase | Acceptance criteria |
|---|---|---|---|---|
| OFF-001 | Downloadable destination packs (guide, audio, map region) with version, progress, storage management, integrity (SHA-256 per file), update detection, and license validation | M | 4 | Corrupted file detected and re-downloaded |
| OFF-002 | Offline reading of guides, playback of audio, access to itineraries | M | 4 | E2E in airplane mode |
| OFF-003 | UI clearly labels offline-capable vs online-only features | M | 1 | "Online only" badge on Feed, Discovery, Messages, AI when offline |
| OFF-004 | Offline allowance by entitlement (free 1 pack, premium 15) | M | 4 | — |
| OFF-005 | Content license expiry respected (packs disabled after `license_expires_at`) | M | 4 | — |

### 4.17 Internationalization: I18N

| ID | Requirement | Pri | Phase | Acceptance criteria |
|---|---|---|---|---|
| I18N-001 | Launch languages: en, es, pt-BR, fr, de. New languages require translation files only | M | 1 | Key-parity test across locales |
| I18N-002 | Locale-aware dates, times, numbers, currencies, units. IANA time zones | M | 1 | — |
| I18N-003 | Localized destination names | M | 1 | — |
| I18N-004 | Full Unicode (emoji, CJK, RTL-ready layouts) | M | 1 | — |
| I18N-005 | Content language filter | M | 1 | — |
| I18N-006 | Machine translation clearly distinguished from original content | M | 4 | — |
| I18N-007 | Server-side error messages localized (`title`/`detail`). `code` is stable | S | 1 | — |

### 4.18 Billing and entitlements: BILL

| ID | Requirement | Pri | Phase | Acceptance criteria |
|---|---|---|---|---|
| BILL-001 | Products: premium monthly, premium annual, individual premium guides, audio tour packages | M | 3 (guides 4) | — |
| BILL-002 | Apple App Store and Google Play billing for in-app digital goods | M | 3 | — |
| BILL-003 | Purchase verification server-side. **Client-reported status is never trusted** | M | 3 | Security test: forged client status rejected |
| BILL-004 | Restore purchases | M | 3 | — |
| BILL-005 | Handle renewals, cancellations, expiration, store grace periods, billing retry, pause, refunds, revocations | M | 3 | State machine tests per provider notification type |
| BILL-006 | Idempotent processing of provider notifications. Out-of-order safe | M | 3 | Replay test |
| BILL-007 | All feature gating centralized in the backend entitlement evaluator | M | 0 | Single `has(user, feature)` function. No other module reads subscription tables |
| BILL-008 | Group admin grace period after lapse (configurable, default 14 days) | M | 3 | — |
| BILL-009 | Admin can grant promotional entitlements (audited) | S | 6 | — |
| BILL-010 | Offers are configurable without a release: subscriptions with any renewal period, passes (Premium for a fixed period, paid once, never renewing, stacking after the current Premium) and content purchases, with localized titles and an order. Prices live with the store or Stripe | M | 3 | Admin API; passes end on the calendar date; "Premium until" spans stacked passes |
| BILL-011 | Every payment, refund and dispute is recorded per user, and travellers can see their purchase history and status. They are told when a payment fails, an asynchronous payment is confirmed, a refund ends a purchase, or Premium that won't renew is about to end | M | 3 | `billing_transactions` ledger never moves backwards; `GET /v1/billing/transactions` shows only the caller's rows |
| BILL-012 | Test and production payments are kept apart: a test key only outside production and a live key only in production, and the webhook ignores events of the other mode | M | 3 | Boot refuses mismatched keys; a live-mode event changes nothing on a test deployment |

### 4.19 Notifications: NOTIF

| ID | Requirement | Pri | Phase | Acceptance criteria |
|---|---|---|---|---|
| NOTIF-001 | In-app notification center | M | 1 | — |
| NOTIF-002 | Push via APNs/FCM with per-type user preferences | M | 3 | — |
| NOTIF-003 | Quiet hours in the user's time zone | S | 3 | — |
| NOTIF-005 | Web Push for the web app (VAPID), through the same device registry and preferences as native push | S | 3 | `POST /v1/users/me/devices {provider: webpush}`. Endpoints stored encrypted and never logged |
| NOTIF-004 | Push payloads minimize sensitive content (no message body if previews are disabled; never location) | M | 3 | — |

### 4.20 Trust, safety and compliance: SAFE

| ID | Requirement | Pri | Phase | Acceptance criteria |
|---|---|---|---|---|
| SAFE-001 | Block users. Effects are immediate and bidirectional across feed, discovery, messaging, groups (where possible) and comments | M | 1 | — |
| SAFE-002 | Report users, posts, comments, messages, groups, challenges. Evidence snapshot captured | M | 1 | — |
| SAFE-003 | Prioritized moderation queue (minor safety, self-harm, threats first) | M | 1 | — |
| SAFE-004 | Media scanning: malware, CSAM hash matching (mandatory before launch), nudity/violence classifier | M | 1 | Rejected media never becomes publicly reachable |
| SAFE-005 | Spam prevention: rate limits, new-account restrictions, link limits, duplicate content detection | M | 1 | — |
| SAFE-006 | Harassment controls: request policies, limits on unsolicited contact, keyword filters for DMs from new connections | M | 2 | — |
| SAFE-007 | Audit logging of admin, moderation, role, entitlement and judging actions | M | 0 | Append-only table |
| SAFE-008 | Safety guidance for meeting strangers (public places, tell a friend, don't share address) | M | 2 | — |
| SAFE-009 | Documented retention schedule and enforcement jobs | M | 1 | [ERD §14](04-database-erd.md) |
| SAFE-010 | GDPR readiness: lawful basis register, DPA with processors, data-transfer mechanism (SCCs), DSR handling, DPIA for discovery | M | 6 | DPIA approved before discovery launch in the EU |
| SAFE-012 | Content that leaves public visibility (removed, deleted, made non-public, indexing consent withdrawn) is purged from web caches via signed revalidation | M | 1 | Propagation ≤ 10 s (target). ISR ≤ 60 s fallback. Signed, idempotent webhook |
| SAFE-013 | Users see their own active restrictions (kind, reason, expiry, appealable) so limits are explained, not silent | S | 1 | `MyAccount.restrictions` reflects active moderation actions |
| SAFE-011 | Abuse detection signals (mass requests, mass reports, rapid destination hopping) | S | 2 | — |

### 4.21 Administration: ADM

| ID | Requirement | Pri | Phase | Acceptance criteria |
|---|---|---|---|---|
| ADM-001 | Admin web console with RBAC (support, moderator, admin, superadmin) | M | 1 (min) / 6 | — |
| ADM-002 | Report queue, content review, enforcement actions (remove, limit, warn, restrict, suspend, ban, reinstate) | M | 1 | — |
| ADM-003 | User lookup with scoped, audited access to sensitive data (just-in-time justification field) | M | 1 | — |
| ADM-004 | Destination and featured content management | S | 1 | — |
| ADM-005 | Subscription configuration (products, grace periods, quotas) | S | 6 | — |
| ADM-007 | Staff (any platform role) must authenticate with MFA. Admin routes reject sessions whose IdP `amr` lacks an MFA method | M | 1 | Non-MFA staff session → `403 mfa_required` on `/v1/admin/*` |
| ADM-008 | Staff session limits on admin routes: 30 min idle, 12 h absolute | M | 1 | Expired → `401 reauthentication_required` |
| ADM-009 | Admin mutations and sensitive reads require an `X-Audit-Justification` header, stored in the audit log | M | 1 | Missing → `400 justification_required`. Contract test enforces the header on every admin mutation |
| ADM-006 | Operational dashboards (moderation SLAs, outbox lag, job failures) | S | 6 | — |

---

## 5. Non-functional requirements: NFR

| ID | Requirement | Target |
|---|---|---|
| NFR-001 | API latency (server-side) | p95 < 300 ms reads, < 500 ms writes. Feed p95 < 300 ms |
| NFR-002 | Message delivery latency (online recipient) | p95 < 500 ms end-to-end within a region |
| NFR-003 | Availability | 99.9 % monthly for API and realtime (excludes AI providers) |
| NFR-004 | Durability | RPO ≤ 5 min (PITR), RTO ≤ 1 h |
| NFR-005 | Scalability | Architecture supports 1 M MAU, 100 k concurrent sockets, by horizontal scaling of process roles |
| NFR-006 | Security | OWASP ASVS L2 for API. TLS 1.2+. Secrets in a managed vault. Dependencies scanned in CI |
| NFR-007 | Privacy | Data minimization, purpose limitation, privacy by default (discovery off, location not stored) |
| NFR-008 | Accessibility | WCAG 2.2 AA for mobile and admin. Dynamic type. Screen reader labels |
| NFR-009 | Mobile performance | Cold start < 2.5 s on mid-range Android. 60 fps scrolling feed |
| NFR-010 | Offline | Trips, downloaded guides and audio work with zero connectivity |
| NFR-011 | Observability | Structured logs with correlation IDs, RED metrics, distributed traces, audit log |
| NFR-012 | Code quality | Strict typing (mypy strict, TS strict). CI gates: lint, type, tests, contract, import boundaries |
| NFR-013 | Test coverage | Domain modules ≥ 90 % line coverage. Overall backend ≥ 80 %. Security tests for every threat with a "test" mitigation |
| NFR-014 | i18n | 100 % of UI strings externalized |
| NFR-015 | Cost | AI spend per active user tracked. Global circuit breaker |

## 6. Release definition

| Release | Phases | Scope summary |
|---|---|---|
| **Alpha (internal)** | 0–1 | Identity, onboarding, destinations, posts, location-based feed, moderation basics |
| **Closed beta** | 2–3 | + Discovery, connections, DMs, premium groups, group chat (sandbox billing) |
| **Open beta** | 4 | + AI itineraries, trips, maps, guides, offline packs |
| **v1.0 launch** | 5–6 | + Challenges, production billing, admin dashboards, store readiness, privacy review |
| **v1.x** | 7 | More destinations, languages, audio tours, ML ranking, partners |

## 7. Assumptions

1. Launch markets: EU, UK, US, Brazil, Mexico, Argentina. Each requires a legal review of age policy, prizes and data transfers.
2. 18+ minimum age at launch simplifies stranger-safety obligations. Revisit per market.
3. Destination boundaries come from openly licensed sources (OSM / geoBoundaries) with attribution.
4. Place data and guide content are licensed or produced in-house. No scraping.
5. The stores' policies require in-app purchase for premium digital features on iOS and Android.

## 8. Open questions (need product or legal decisions)

| # | Question | Default until decided |
|---|---|---|
| Q-1 | ~~IdP vendor (Auth0 / Cognito / Firebase / Ory / Keycloak)?~~ | **Resolved (v1.4):** Supabase Auth ([ADR-0020](adr/0020-supabase-auth-identity-provider.md)). Dev adapter kept for development and tests |
| Q-2 | Billing via direct store APIs or RevenueCat? | Direct, behind the `BillingProvider` port |
| Q-3 | Map tile provider permitting offline packs (MapTiler, Stadia, Protomaps self-hosted)? | MapLibre + PMTiles, provider TBD |
| Q-4 | Should the requester see "declined", or only "pending until expiry"? | Requester sees `declined` (honest UX); cooldown enforced |
| Q-5 | Free AI quota (generations/month)? | 5 generations, 0 replans (replan is premium) |
| Q-6 | Group admin grace period length? | 14 days |
| Q-7 | Age verification beyond self-attestation in specific markets (UK OSA, US state laws)? | Self-attestation + reporting. Legal review before launch |
| Q-8 | Cloud provider? | **Database decided: Supabase** (ADR-0018, `us-east-1`, Free → Pro). **Backend hosting decided for staging: Vercel serverless** (ADR-0019, `iad1`, next to Supabase). Render/Docker (`render.yaml`) is ready for long-running roles once a card is on file. Web is on Vercel. Open sub-question: keep `us-east-1` or create an EU project before launch (GDPR transfers) |

## 9. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Stalking or harassment via discovery | Severe | Coarse location only, opt-in, TTL, rate limits, blocks, reporting, DPIA ([08](08-privacy-security-threat-model.md)) |
| Empty-content cold start in new destinations | High | Seeded editorial content, fallback chain, creator programme |
| Store rejection (UGC, meeting strangers, prizes) | High | Report/block on all UGC, moderation SLAs, EULA, no paid-entry contests |
| AI hallucinated facts (hours, safety) | Medium | Schema without such fields, grounding, attribution |
| Prize legal exposure | Medium | Non-cash only, review gate, jurisdiction notices |
| Cost overrun (AI, media) | Medium | Quotas, circuit breaker, CDN, media size limits |
