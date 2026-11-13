# Architecture Decision Records

ADRs use the format **Context → Decision → Consequences → Alternatives**. Statuses are `Proposed`, `Accepted`, `Superseded by ADR-xxxx` and `Deprecated`. To change a decision, add a new ADR that supersedes the old one. Never rewrite an accepted ADR's decision.

**Numbering:** take the next free number at the moment of writing. Several workstreams (backend/mobile and web) add ADRs in parallel, so check this folder first. **This index is append-only:** add your row, don't reorder or remove others.

| ADR | Title | Area | Status |
|---|---|---|---|
| [0001](0001-modular-monolith.md) | Modular monolith with enforced module boundaries | Backend | Accepted |
| [0002](0002-contract-first-openapi.md) | Contract-first REST API (OpenAPI 3.1) and shared conventions | Platform | Accepted |
| [0003](0003-oidc-idp-with-platform-sessions.md) | Managed OIDC identity provider + platform-issued sessions | Identity | Accepted (vendor Proposed). Amended by 0011 |
| [0004](0004-postgres-outbox-and-job-queue.md) | Transactional outbox and Postgres-backed job queue | Backend | Accepted |
| [0005](0005-coarse-location-discovery.md) | Traveler discovery uses destinations, never coordinates | Privacy | Accepted |
| [0006](0006-central-entitlement-evaluation.md) | Central server-side entitlement evaluator | Billing | Accepted |
| [0007](0007-data-conventions.md) | UUIDv7 keys, text+CHECK enums, UTC timestamps | Data | Accepted |
| [0008](0008-maps-provider-strategy.md) | MapLibre + offline-licensable tiles; routing via provider | Maps | Proposed |
| [0009](0009-web-monorepo-layout.md) | Web monorepo layout with npm workspaces | Web | Accepted |
| [0010](0010-nextjs-for-web-and-admin.md) | One Next.js app for public site, traveler web app and admin (supersedes the Vite admin in doc 02) | Web | Accepted |
| [0011](0011-web-bff-cookie-sessions.md) | Web sessions through a BFF with sealed HTTP-only cookies | Web / Identity | Accepted |
| [0012](0012-web-billing-provider.md) | Web subscriptions through Stripe behind the billing port | Web / Billing | Proposed |
| [0013](0013-realtime-tickets-for-browsers.md) | Single-use realtime tickets for browser WebSocket auth | Web / Realtime | Accepted |
| [0014](0014-web-maps-maplibre.md) | MapLibre GL JS for web maps (tile vendor per 0008) | Web / Maps | Accepted |
| [0015](0015-expo-react-native.md) | Expo (dev builds) for the React Native app | Mobile | Accepted |
| [0016](0016-no-e2ee-in-v1.md) | No end-to-end encryption for messages in v1 | Messaging | Accepted |
| [0017](0017-billing-direct-store-integration.md) | Direct App Store / Play integration behind a billing port | Billing | Proposed |
| [0018](0018-supabase-managed-postgres.md) | Supabase as the managed PostgreSQL provider (database only; Data API locked down) | Data / Infra | Accepted (superseded by 0028, reinstated by 0029) |
| [0019](0019-backend-api-hosting.md) | Backend API hosting: Vercel serverless (staging), Render/Docker ready for long-running roles | Infra | Superseded by 0028 (cutover pending) |
| [0020](0020-supabase-auth-identity-provider.md) | Supabase Auth as the managed identity provider (publishable key for Auth only; staff MFA via `aal2`) | Identity | Superseded by 0028 (cutover pending) |
| [0021](0021-rate-limit-stores-and-client-ip.md) | Rate-limit counter stores (Redis, PostgreSQL fallback for serverless) and client IP trust (BFF forwarding secret) | Platform / Security | Accepted |
| [0022](0022-media-object-storage.md) | Media object storage through an S3-compatible port (own SigV4; Supabase Storage recommended; in-process store for dev/test) | Media / Infra | Accepted. Amended by 0028 (Cloud Storage) |
| [0023](0023-realtime-delivery-and-hosting.md) | Realtime delivery through per-user channels (gateway inside the API app, Memory/Redis bus, REST fallback on serverless) | Messaging / Infra | Accepted |
| [0024](0024-ai-provider-and-cost-controls.md) | AI provider port with a Claude adapter (official SDK, structured outputs), asynchronous generations, quotas and database-backed spend/provider breakers | AI | Accepted |
| [0025](0025-place-data-from-openstreetmap.md) | Place data from OpenStreetMap (ODbL) through a PlaceSource port, stored as lat/lng with bbox + haversine nearby search | Destinations / AI | Accepted |
| [0026](0026-offline-packages-signed-manifests.md) | Offline packages: prebuilt, Ed25519-signed manifests (key in client-config), per-device licenses with quota, token download URLs redirecting to storage | Guides / Mobile | Accepted |
| [0027](0027-destination-boundaries-from-openstreetmap.md) | Destination boundaries from OSM administrative relations (ODbL), assembled and repaired in PostGIS, loaded by an operator command; source recorded per polygon | Destinations | Accepted |
| [0028](0028-firebase-platform-and-railway-hosting.md) | Firebase platform: Firebase Auth (account check at sign-in, Admin API deletion), Cloud SQL for PostgreSQL through the Cloud SQL Python Connector, Cloud Storage via the S3 port, FCM; API and worker on Railway | Identity / Data / Infra | Accepted. Amended by 0029 (database and media stay on Supabase) |
| [0029](0029-supabase-free-tier-for-data-and-media.md) | Supabase free tier for the database (session pooler) and media (S3 buckets); Firebase for identity and push; Google Drive rejected as a media store | Data / Infra | Accepted |
| [0030](0030-companions-map-ip-start-and-area-pins.md) | Companions map: approximate start from the IP address (local DB-IP Lite lookup, nothing stored, nobody placed without Search), travellers drawn around the area they share, MapLibre GL JS + OpenFreeMap in a locked-down WebView | Location / Mobile | Accepted. Amends PRD LOC-004 |
| [0031](0031-payments-store-first-stripe-web-ledger.md) | Payments: App Store / Google Play billing in the apps (all plans are digital), Stripe Checkout on the web, no external payment links until legal confirms a region; configurable offers and passes, one money ledger, webhooks that re-read Stripe objects, duplicate protection, test/live separation | Billing | Accepted. Confirms 0012 and 0017 |
| [0032](0032-standalone-staff-console.md) | Staff console as a separate static app (`admin/`, React + Vite) on its own origin (Firebase Hosting `travel-buddy-staff`): Firebase password + TOTP second factor, in-memory tokens, strict CSP, a work reason sent as the audit justification; API gains account search, overview metrics, ledger and staff roles | Admin / Security | Accepted. Amends 0010 (admin area only) |
| [0033](0033-mobile-realtime-and-offline-chat.md) | Realtime chat on mobile over the API's WebSocket gateway (typing, receipts with avatars, instant notifications), PostgreSQL LISTEN/NOTIFY fanout when there is no Redis, an offline-first outbox and history cache, and the API next to the database's region | Messaging / Infra | Accepted. Amends 0023 |
| [0034](0034-chat-gifts.md) | Chat gifts: a fixed catalog of free illustrated presents shipped with the apps, sent as a `gift` message in direct chats and opened once by the recipient; no money value, no purchase, no text of their own | Messaging / Product | Accepted |
| [0035](0035-world-gazetteer-and-place-search.md) | World gazetteer from open data (GeoNames towns of 5,000+ people, Wikidata tourist places) loaded into the catalog outside the directory; points resolve to the nearest town weighed by size; `GET /v1/destinations/suggest` and a "Where to?" search sheet with no streets; precise location as the traveller's choice | Location / Product | Accepted |

Template: [`template.md`](template.md).
