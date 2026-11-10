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
| [0018](0018-supabase-managed-postgres.md) | Supabase as the managed PostgreSQL provider (database only; Data API locked down) | Data / Infra | Accepted |
| [0019](0019-backend-api-hosting.md) | Backend API hosting: Vercel serverless (staging), Render/Docker ready for long-running roles | Infra | Accepted |
| [0020](0020-supabase-auth-identity-provider.md) | Supabase Auth as the managed identity provider (publishable key for Auth only; staff MFA via `aal2`) | Identity | Accepted |
| [0021](0021-rate-limit-stores-and-client-ip.md) | Rate-limit counter stores (Redis, PostgreSQL fallback for serverless) and client IP trust (BFF forwarding secret) | Platform / Security | Accepted |
| [0022](0022-media-object-storage.md) | Media object storage through an S3-compatible port (own SigV4; Supabase Storage recommended; in-process store for dev/test) | Media / Infra | Accepted |
| [0023](0023-realtime-delivery-and-hosting.md) | Realtime delivery through per-user channels (gateway inside the API app, Memory/Redis bus, REST fallback on serverless) | Messaging / Infra | Accepted |
| [0024](0024-ai-provider-and-cost-controls.md) | AI provider port with a Claude adapter (official SDK, structured outputs), asynchronous generations, quotas and database-backed spend/provider breakers | AI | Accepted |
| [0025](0025-place-data-from-openstreetmap.md) | Place data from OpenStreetMap (ODbL) through a PlaceSource port, stored as lat/lng with bbox + haversine nearby search | Destinations / AI | Accepted |
| [0026](0026-offline-packages-signed-manifests.md) | Offline packages: prebuilt, Ed25519-signed manifests (key in client-config), per-device licenses with quota, token download URLs redirecting to storage | Guides / Mobile | Accepted |
| [0027](0027-destination-boundaries-from-openstreetmap.md) | Destination boundaries from OSM administrative relations (ODbL), assembled and repaired in PostGIS, loaded by an operator command; source recorded per polygon | Destinations | Accepted |

Template: [`template.md`](template.md).
