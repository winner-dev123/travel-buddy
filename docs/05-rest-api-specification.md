# 05 — REST API Specification

| | |
|---|---|
| **Status** | Draft v1.0 — Phase 0 |
| **Normative source** | [`contracts/openapi/openapi.yaml`](../contracts/openapi/openapi.yaml) (OpenAPI 3.1). **If this document and the contract disagree, the contract wins.** Fix the document. |
| **Related** | [Architecture §5 (conventions)](02-system-architecture.md#5-platform-wide-api-conventions) · [ERD](04-database-erd.md) · [Realtime protocol](06-realtime-messaging-protocol.md) · [Entitlement policy](07-subscription-entitlement-policy.md) · [Threat model](08-privacy-security-threat-model.md) · ADR-0011 (web BFF sessions) · ADR-0012 (web billing) · ADR-0013 (realtime tickets) |

This document is the human-readable companion to the contract. It explains *why* the API looks the way it does, who may call what, how traffic is limited, and what every error code means. Field-level detail lives only in the OpenAPI file.

---

## 1. Conventions recap

The platform-wide conventions are defined once, in [architecture §5](02-system-architecture.md#5-platform-wide-api-conventions). They are summarized here only where the contract adds precision.

| Topic | Contract rule |
|---|---|
| Base path | `/v1/...`. Probes `/health/live` and `/health/ready` are unversioned. |
| Media type | `application/json` (UTF-8). Errors are `application/problem+json`. |
| IDs and time | UUIDv7 strings. RFC 3339 UTC timestamps. `YYYY-MM-DD` local dates (destination time zone). |
| Nullability | Optional-but-known fields are **present with `null`**, not omitted (`type: [x, 'null']`). Request bodies use `additionalProperties: false`, so unknown fields are rejected with `validation_failed`. Clients must **ignore unknown response fields**, because additive changes are not breaking. |
| Pagination | `?cursor=&limit=` (1–100, default 20). Response is `{data, page: {next_cursor, has_more}}`. The feed adds `page.reset` and a top-level `context`. **Exception:** message history uses a seq keyset (`before_seq` / `after_seq`) and returns `page: {has_more, oldest_seq, newest_seq}`, because clients must address absolute positions to repair gaps (see [doc 06 §6](06-realtime-messaging-protocol.md#6-ordering-gaps-and-catch-up)). |
| Idempotency | Operations marked `x-idempotency: required` must send `Idempotency-Key: <uuid>`. A replay returns the original status and body plus `Idempotent-Replayed: true`. The same key with a different body returns `409 idempotency_key_reused`. A concurrent duplicate returns `409 idempotency_key_in_progress`. `PUT` and `DELETE` are naturally idempotent (repeating them is safe and returns the same result). |
| Optimistic concurrency | Aggregates with `version` (groups, group settings, trips, challenges) return `ETag: "<version>"` and require `If-Match` on mutation. A mismatch returns `412`, and a missing header returns `428 precondition_required`. |
| Correlation | `X-Request-ID` is accepted on every operation (8–128 chars of `[A-Za-z0-9._-]`), otherwise generated. It is always echoed and is included in every problem body. |
| Localization | `Accept-Language` localizes UI strings, destination and place names, and notification text. User-generated content is returned in its original language. Machine translation is a separate resource (`/v1/posts/{id}/translation`, `machine_translated: true`). |
| Extensions | `x-phase` (delivery phase), `x-requirements` (PRD IDs), `x-rate-limit-class`, `x-idempotency`, `x-entitlement` (billing feature gate), `x-platform-permission` (admin RBAC), `x-dev-only` (development/test only). |

### 1.1 Clients

Three first-party clients use the API. The API surface is the same for all three. Differences are confined to authentication transport and billing.

| Client | Auth transport | Realtime auth | Purchases |
|---|---|---|---|
| iOS / Android (React Native) | `Authorization: Bearer` from the secure enclave. `client: ios\|android` at login. | `auth {access_token}` frame | App Store / Google Play → `POST /v1/billing/purchases/verify` |
| Web (Next.js BFF, ADR-0011) | The BFF holds platform tokens in a sealed HTTP-only cookie and calls the API with Bearer. Browsers never see tokens. `client: web` at login. | `POST /v1/realtime/tickets` (via BFF) → `auth {ticket}` frame. The Origin header is allow-listed. | Stripe Checkout → `POST /v1/billing/checkout-sessions` / `portal-sessions`, entitlement via Stripe webhook |
| Admin console (web) | Same as web, plus platform roles in the token | Same as web | — |

### 1.2 Authentication flow (all clients)

1. The client authenticates with the OIDC identity provider (email/password, Apple, Google). In development and test, the **dev IdP** (`POST /v1/dev/idp/token`, `x-dev-only`, 404 in staging/production) mints an EdDSA test token that goes through the *same* verifier.
2. `POST /v1/auth/register` (first time: `birth_date` for the age gate, accepted terms and privacy versions, locale) or `POST /v1/auth/login`, with body `{id_token, client, nonce?, device?}`. There is **no `provider` field**: the verifier is selected from the token's `iss`.
3. The response is `AuthResult {tokens, user: Me, is_new_user}`. The access token lives 15 minutes. The refresh token is opaque and rotates on every use.
4. `POST /v1/auth/refresh`. **Reuse leeway:** presenting the *immediately previous* refresh token within **30 s** of its rotation returns the **same** successor pair, so parallel refreshes from browser tabs or concurrent requests do not log the user out. Reuse after 30 s, or of any older token, revokes the whole token family with `401 refresh_token_reused`, and open WebSockets get `session.revoked`.
5. `GET /v1/users/me` returns the bootstrap object `Me {account, profile, preferences, privacy, roles[], onboarding_completed, browse_destination, entitlements}`. `entitlements` is the same `Entitlements` object as `GET /v1/billing/entitlements`.

---

## 2. Resource map

The tables below are **generated from the contract** (`x-phase`, `security`, `x-idempotency`, `x-rate-limit-class`, `x-entitlement`, `x-requirements`). Regenerate them after changing the contract instead of editing by hand.

Legend. **Auth:** `bearer` = platform access token. `optional` = anonymous allowed, richer response when authenticated. `none` = anonymous. `signature` = provider-signed webhook. `bearer + perm` = platform RBAC permission. **Idempotency:** `required` = `Idempotency-Key` header. `natural` = PUT/DELETE semantics. **Requirements:** PRD IDs (placeholders until the PRD numbering is reconciled).

<!-- BEGIN GENERATED: resource-map -->
#### health

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `GET /health/live` | 0 | none | — | none |  | NFR-010 |
| `GET /health/ready` | 0 | none | — | none |  | NFR-010 |

#### config

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `GET /v1/client-config` | 0 | optional | — | read |  | I18N-001 |
| `GET /v1/catalog/travel-interests` | 1 | optional | — | read |  | AUTH-010, PROF-004, I18N-003 |

#### auth

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `POST /v1/auth/register` | 1 | none | required | auth |  | AUTH-001, AUTH-002, AUTH-003, SAFE-001 |
| `POST /v1/auth/login` | 1 | none | — | auth |  | AUTH-004, AUTH-005 |
| `POST /v1/auth/refresh` | 1 | none | — | auth |  | AUTH-006, AUTH-009 |
| `POST /v1/auth/logout` | 1 | bearer | — | write |  | AUTH-007 |
| `POST /v1/dev/idp/token` | 1 | none (dev only) | — | auth |  | AUTH-001 |
| `GET /v1/dev/idp/jwks.json` | 1 | none (dev only) | — | read |  | AUTH-001 |

#### me

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `GET /v1/users/me` | 1 | bearer | — | read |  | PROF-001, AUTH-010, BILL-002, SAFE-013 |
| `PATCH /v1/users/me` | 1 | bearer | — | write |  | PROF-001, PROF-002, PROF-004 |
| `POST /v1/users/me/onboarding/complete` | 1 | bearer | — | write |  | AUTH-010, FEED-001 |
| `GET /v1/users/me/sessions` | 1 | bearer | — | read |  | AUTH-008 |
| `DELETE /v1/users/me/sessions/{sessionId}` | 1 | bearer | natural | write |  | AUTH-008 |
| `GET /v1/users/me/preferences` | 1 | bearer | — | read |  | PROF-005, I18N-002 |
| `PATCH /v1/users/me/preferences` | 1 | bearer | — | write |  | PROF-005, I18N-002 |
| `GET /v1/users/me/privacy` | 1 | bearer | — | read |  | PROF-006, DISC-001, SAFE-010, PROF-008 |
| `PATCH /v1/users/me/privacy` | 1 | bearer | — | write |  | PROF-006, DISC-001, DISC-002, PROF-008, SAFE-012 |
| `GET /v1/users/me/consents` | 1 | bearer | — | read |  | AUTH-009 |
| `POST /v1/users/me/consents` | 1 | bearer | — | write |  | AUTH-009, DISC-001 |
| `POST /v1/users/me/deletion` | 1 | bearer | required | sensitive |  | AUTH-010 |
| `DELETE /v1/users/me/deletion` | 1 | bearer | natural | write |  | AUTH-010 |
| `POST /v1/users/me/data-exports` | 1 | bearer | required | sensitive |  | AUTH-011 |
| `GET /v1/users/me/data-requests` | 1 | bearer | — | read |  | AUTH-010, AUTH-011 |

#### profiles

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `GET /v1/users/{userId}` | 1 | bearer | — | read |  | PROF-005, SAFE-001, PROF-008 |
| `GET /v1/users/by-handle/{handle}` | 1 | bearer | — | read |  | PROF-005, PROF-008 |
| `GET /v1/users/{userId}/posts` | 1 | bearer | — | read |  | POST-008, SAFE-001 |
| `GET /v1/users/search` | 2 | bearer | — | search |  | PROF-003 |

#### destinations

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `GET /v1/destinations` | 1 | optional | — | read |  | DEST-006, DEST-004, AUTH-012 |
| `GET /v1/destinations/search` | 1 | optional | — | search |  | DEST-001, LOC-002, I18N-004 |
| `GET /v1/destinations/featured` | 1 | optional | — | read |  | DEST-003, DEST-004 |
| `GET /v1/destinations/lookup` | 1 | optional | — | read |  | DEST-002, DEST-004 |
| `GET /v1/destinations/resolve` | 1 | bearer | — | read |  | LOC-001, LOC-008 |
| `GET /v1/destinations/{destinationId}` | 1 | optional | — | read |  | DEST-002 |
| `GET /v1/destinations/{destinationId}/children` | 1 | optional | — | read |  | DEST-002, LOC-002 |

#### places

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `GET /v1/places/nearby` | 1 | bearer | — | read |  | LOC-009, DEST-003 |
| `GET /v1/places/search` | 1 | bearer | — | search |  | DEST-003, POST-004 |
| `GET /v1/places/{placeId}` | 1 | optional | — | read |  | DEST-003, AI-006 |

#### location

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `GET /v1/users/me/browse-destination` | 1 | bearer | — | read |  | LOC-003 |
| `PUT /v1/users/me/browse-destination` | 1 | bearer | natural | write |  | LOC-003, LOC-004, FEED-003 |
| `DELETE /v1/users/me/browse-destination` | 1 | bearer | natural | write |  | LOC-003 |
| `GET /v1/users/me/upcoming-destinations` | 1 | bearer | — | read |  | LOC-005, FEED-001 |
| `POST /v1/users/me/upcoming-destinations` | 1 | bearer | — | write |  | LOC-005, FEED-001, AUTH-010 |
| `DELETE /v1/users/me/upcoming-destinations/{selectionId}` | 1 | bearer | natural | write |  | LOC-005 |
| `GET /v1/users/me/discovery-location` | 2 | bearer | — | read |  | DISC-003, LOC-006 |
| `PUT /v1/users/me/discovery-location` | 2 | bearer | natural | write |  | DISC-001, DISC-003, DISC-004, LOC-006, LOC-007, SAFE-011 |
| `DELETE /v1/users/me/discovery-location` | 2 | bearer | natural | write |  | DISC-005 |

#### feed

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `GET /v1/feed` | 1 | bearer | — | read |  | FEED-001, FEED-002, FEED-003, FEED-004, FEED-020, FEED-021, LOC-007, LOC-008 |
| `POST /v1/feed/feedback` | 1 | bearer | — | write |  | FEED-022 |
| `GET /v1/public/posts` | 1 | none | — | guest |  | AUTH-012, FEED-005, PROF-008 |
| `GET /v1/public/posts/{postId}` | 1 | none | — | guest |  | AUTH-012, POST-005, PROF-008 |

#### posts

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `POST /v1/posts` | 1 | bearer | required | write |  | POST-001, POST-002, POST-003, POST-004, POST-005, SAFE-005 |
| `GET /v1/posts/{postId}` | 1 | bearer | — | read |  | POST-008, SAFE-001 |
| `PATCH /v1/posts/{postId}` | 1 | bearer | — | write |  | POST-006 |
| `DELETE /v1/posts/{postId}` | 1 | bearer | natural | write |  | POST-006 |
| `GET /v1/posts/{postId}/reactions` | 1 | bearer | — | read |  | POST-010 |
| `POST /v1/posts/{postId}/reactions` | 1 | bearer | — | write |  | POST-010 |
| `DELETE /v1/posts/{postId}/reactions/me` | 1 | bearer | natural | write |  | POST-010 |
| `GET /v1/posts/{postId}/comments` | 1 | bearer | — | read |  | POST-011 |
| `POST /v1/posts/{postId}/comments` | 1 | bearer | required | write |  | POST-011 |
| `PATCH /v1/comments/{commentId}` | 1 | bearer | — | write |  | POST-011 |
| `DELETE /v1/comments/{commentId}` | 1 | bearer | natural | write |  | POST-011, POST-007 |
| `GET /v1/comments/{commentId}/replies` | 1 | bearer | — | read |  | POST-011 |
| `PUT /v1/posts/{postId}/bookmark` | 1 | bearer | natural | write |  | POST-005 |
| `DELETE /v1/posts/{postId}/bookmark` | 1 | bearer | natural | write |  | POST-005 |
| `GET /v1/users/me/bookmarks` | 1 | bearer | — | read |  | POST-005 |
| `POST /v1/posts/{postId}/shares` | 1 | bearer | — | write |  | POST-005, AUTH-012 |
| `GET /v1/posts/{postId}/translation` | 7 | bearer | — | ai |  | I18N-006, POST-010 |

#### follows

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `GET /v1/users/{userId}/followers` | 1 | bearer | — | read |  | POST-006 |
| `GET /v1/users/{userId}/following` | 1 | bearer | — | read |  | POST-006 |
| `PUT /v1/users/{userId}/follow` | 1 | bearer | natural | write |  | POST-006 |
| `DELETE /v1/users/{userId}/follow` | 1 | bearer | natural | write |  | POST-006 |
| `GET /v1/users/me/follow-requests` | 1 | bearer | — | read |  | POST-006 |
| `POST /v1/users/me/follow-requests/{userId}/approve` | 1 | bearer | — | write |  | POST-006 |
| `POST /v1/users/me/follow-requests/{userId}/decline` | 1 | bearer | — | write |  | POST-006 |

#### safety

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `GET /v1/users/me/blocks` | 1 | bearer | — | read |  | SAFE-001 |
| `PUT /v1/users/{userId}/block` | 1 | bearer | natural | write |  | SAFE-001, CONN-009, DM-012, DISC-010 |
| `DELETE /v1/users/{userId}/block` | 1 | bearer | natural | write |  | SAFE-001 |
| `POST /v1/reports` | 1 | bearer | — | sensitive |  | SAFE-002 |

#### media

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `POST /v1/media/uploads` | 1 | bearer (`editorial`: + `content.destinations.write`) | required | media_upload |  | POST-002, SAFE-005, POST-004, SAFE-004, DEST-007 |
| `GET /v1/media/{mediaId}` | 1 | bearer | — | read |  | POST-002 |
| `POST /v1/media/{mediaId}/finalize` | 1 | bearer | — | media_upload |  | POST-002, SAFE-005, SAFE-004 |

#### discovery

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `GET /v1/travelers/discover` | 2 | bearer | — | discovery |  | DISC-001, DISC-003, DISC-006, DISC-007, DISC-008, DISC-010, SAFE-011 |

#### connections

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `GET /v1/connections/requests` | 2 | bearer | — | read |  | CONN-001, CONN-004 |
| `POST /v1/connections/requests` | 2 | bearer | required | contact |  | CONN-001, CONN-002, CONN-003, CONN-005 |
| `POST /v1/connections/requests/{connectionRequestId}/accept` | 2 | bearer | — | write |  | CONN-005 |
| `POST /v1/connections/requests/{connectionRequestId}/decline` | 2 | bearer | — | write |  | CONN-006 |
| `POST /v1/connections/requests/{connectionRequestId}/cancel` | 2 | bearer | — | write |  | CONN-007 |
| `GET /v1/connections` | 2 | bearer | — | read |  | CONN-008 |
| `DELETE /v1/connections/{userId}` | 2 | bearer | natural | write |  | CONN-009 |
| `GET /v1/users/{userId}/relationship` | 2 | bearer | — | read |  | CONN-001 |

#### messaging

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `GET /v1/conversations` | 3 | bearer | — | read |  | DM-001, GCHAT-001 |
| `POST /v1/conversations` | 3 | bearer | — | write |  | DM-001, DM-002 |
| `GET /v1/conversations/{conversationId}` | 3 | bearer | — | read |  | DM-001, DM-011 |
| `GET /v1/conversations/{conversationId}/messages` | 3 | bearer | — | read |  | DM-003, DM-010, DM-011 |
| `POST /v1/conversations/{conversationId}/messages` | 3 | bearer | required | message |  | DM-004, DM-005, DM-012, DM-013, GCHAT-002, SAFE-005 |
| `PATCH /v1/conversations/{conversationId}/messages/{messageId}` | 3 | bearer | — | message |  | DM-010 |
| `DELETE /v1/conversations/{conversationId}/messages/{messageId}` | 3 | bearer | natural | write |  | DM-010, GCHAT-004 |
| `PUT /v1/conversations/{conversationId}/messages/{messageId}/reactions/{emoji}` | 3 | bearer | natural | write |  | GCHAT-003 |
| `DELETE /v1/conversations/{conversationId}/messages/{messageId}/reactions/{emoji}` | 3 | bearer | natural | write |  | GCHAT-003 |
| `GET /v1/conversations/{conversationId}/threads/{messageId}` | 3 | bearer | — | read |  | GCHAT-004 |
| `PUT /v1/conversations/{conversationId}/receipts` | 3 | bearer | natural | write |  | DM-006, DM-007 |
| `PUT /v1/conversations/{conversationId}/mute` | 3 | bearer | natural | write |  | DM-008, GCHAT-005 |
| `POST /v1/conversations/{conversationId}/clear` | 3 | bearer | — | write |  | DM-009 |
| `GET /v1/conversations/{conversationId}/pins` | 3 | bearer | — | read |  | GCHAT-006 |
| `PUT /v1/conversations/{conversationId}/pins/{messageId}` | 3 | bearer | natural | write |  | GCHAT-006 |
| `DELETE /v1/conversations/{conversationId}/pins/{messageId}` | 3 | bearer | natural | write |  | GCHAT-006 |

#### realtime

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `POST /v1/realtime/tickets` | 3 | bearer | — | realtime_ticket |  | DM-003, AUTH-011 |

#### groups

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `GET /v1/groups` | 3 | bearer | — | read |  | GRP-010 |
| `POST /v1/groups` | 3 | bearer | required | write | `groups.create` | GRP-001, GRP-002, GRP-003, GRP-013 |
| `GET /v1/groups/{groupId}` | 3 | bearer | — | read |  | GRP-010, GRP-011 |
| `PATCH /v1/groups/{groupId}` | 3 | bearer | — | write |  | GRP-004 |
| `POST /v1/groups/{groupId}/archive` | 3 | bearer | — | write |  | GRP-005, GRP-011 |
| `GET /v1/groups/{groupId}/settings` | 3 | bearer | — | read |  | GRP-006 |
| `PATCH /v1/groups/{groupId}/settings` | 3 | bearer | — | write |  | GRP-006 |
| `GET /v1/groups/{groupId}/roles` | 3 | bearer | — | read |  | GRP-007 |
| `GET /v1/groups/{groupId}/members` | 3 | bearer | — | read |  | GRP-012 |
| `PATCH /v1/groups/{groupId}/members/{userId}` | 3 | bearer | — | write |  | GRP-007 |
| `DELETE /v1/groups/{groupId}/members/{userId}` | 3 | bearer | natural | write |  | GRP-007, GCHAT-004, GCHAT-007, GRP-009 |
| `PUT /v1/groups/{groupId}/members/{userId}/restriction` | 3 | bearer | natural | write |  | GCHAT-004, GRP-009 |
| `DELETE /v1/groups/{groupId}/members/{userId}/restriction` | 3 | bearer | natural | write |  | GCHAT-004 |
| `POST /v1/groups/{groupId}/leave` | 3 | bearer | — | write |  | GRP-013 |
| `GET /v1/groups/{groupId}/invitations` | 3 | bearer | — | read |  | GRP-005 |
| `POST /v1/groups/{groupId}/invitations` | 3 | bearer | required | contact |  | GRP-005, GRP-009, SAFE-005 |
| `DELETE /v1/groups/{groupId}/invitations/{invitationId}` | 3 | bearer | natural | write |  | GRP-005 |
| `GET /v1/users/me/group-invitations` | 3 | bearer | — | read |  | GRP-005 |
| `POST /v1/group-invitations/{invitationId}/accept` | 3 | bearer | — | write |  | GRP-005, GRP-008 |
| `POST /v1/group-invitations/{invitationId}/decline` | 3 | bearer | — | write |  | GRP-005 |
| `POST /v1/group-invitations/preview` | 3 | bearer | — | sensitive |  | GRP-005 |
| `POST /v1/group-invitations/redeem` | 3 | bearer | — | sensitive |  | GRP-005, GRP-012 |
| `GET /v1/groups/{groupId}/join-requests` | 3 | bearer | — | read |  | GRP-006 |
| `POST /v1/groups/{groupId}/join-requests` | 3 | bearer | required | contact |  | GRP-006 |
| `POST /v1/groups/{groupId}/join-requests/{joinRequestId}/approve` | 3 | bearer | — | write |  | GRP-006 |
| `POST /v1/groups/{groupId}/join-requests/{joinRequestId}/reject` | 3 | bearer | — | write |  | GRP-006 |
| `POST /v1/groups/{groupId}/ownership-transfers` | 3 | bearer | — | write |  | GRP-010 |
| `POST /v1/groups/{groupId}/ownership-transfers/{transferId}/{action}` | 3 | bearer | — | write |  | GRP-010 |
| `POST /v1/groups/{groupId}/announcements` | 3 | bearer | required | message |  | GCHAT-007 |

#### challenges

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `GET /v1/users/{userId}/badges` | 5 | bearer | — | read |  | CHAL-012 |
| `GET /v1/groups/{groupId}/challenges` | 5 | bearer | — | read |  | CHAL-001, CHAL-010 |
| `POST /v1/groups/{groupId}/challenges` | 5 | bearer | required | write | `challenges.create` | CHAL-001, CHAL-002, CHAL-003, CHAL-014 |
| `GET /v1/challenges/{challengeId}` | 5 | bearer | — | read |  | CHAL-010, CHAL-008 |
| `PATCH /v1/challenges/{challengeId}` | 5 | bearer | — | write |  | CHAL-004 |
| `GET /v1/challenges/{challengeId}/manage` | 5 | bearer | — | read |  | CHAL-004 |
| `POST /v1/challenges/{challengeId}/publish` | 5 | bearer | — | write |  | CHAL-005, CHAL-006 |
| `POST /v1/challenges/{challengeId}/cancel` | 5 | bearer | — | write |  | CHAL-007 |
| `GET /v1/challenges/{challengeId}/hints` | 5 | bearer | — | read |  | CHAL-011 |
| `GET /v1/challenges/{challengeId}/teams` | 5 | bearer | — | read |  | CHAL-012 |
| `POST /v1/challenges/{challengeId}/teams` | 5 | bearer | — | write |  | CHAL-012, CHAL-013 |
| `POST /v1/challenges/{challengeId}/teams/{teamId}/join` | 5 | bearer | — | write |  | CHAL-012 |
| `GET /v1/challenges/{challengeId}/submissions` | 5 | bearer | — | read |  | CHAL-014, CHAL-006 |
| `POST /v1/challenges/{challengeId}/submissions` | 5 | bearer | required | submission |  | CHAL-014, CHAL-015, CHAL-016, CHAL-009, CHAL-005 |
| `POST /v1/challenges/{challengeId}/submissions/{submissionId}/judgement` | 5 | bearer | — | write |  | CHAL-006, CHAL-009 |
| `GET /v1/challenges/{challengeId}/answers` | 5 | bearer | — | sensitive |  | CHAL-008 |
| `GET /v1/challenges/{challengeId}/results` | 5 | bearer | — | read |  | CHAL-011 |
| `POST /v1/challenges/{challengeId}/results/publish` | 5 | bearer | — | write |  | CHAL-011, CHAL-010 |
| `POST /v1/challenges/{challengeId}/winners/{winnerId}/{action}` | 5 | bearer | — | write |  | CHAL-010 |
| `GET /v1/challenges/{challengeId}/disputes` | 5 | bearer | — | read |  | CHAL-016 |
| `POST /v1/challenges/{challengeId}/disputes` | 5 | bearer | — | sensitive |  | CHAL-016 |
| `POST /v1/challenges/{challengeId}/disputes/{disputeId}/resolve` | 5 | bearer | — | write |  | CHAL-016 |
| `GET /v1/challenges/{challengeId}/fulfillments` | 5 | bearer | — | read |  | CHAL-015 |
| `POST /v1/challenges/{challengeId}/fulfillments/{fulfillmentId}/transitions` | 5 | bearer | — | write |  | CHAL-015 |
| `GET /v1/users/me/rewards` | 5 | bearer | — | read |  | CHAL-015 |

#### ai

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `POST /v1/ai/itineraries/generate` | 4 | bearer | required | ai |  | AI-001, AI-002, AI-003, AI-004, AI-005, AI-006, AI-010 |
| `GET /v1/ai/generations/{generationId}` | 4 | bearer | — | read |  | AI-001, AI-009 |
| `POST /v1/ai/trips/{tripId}/replan` | 4 | bearer | required | ai | `ai.trip_replan` | AI-007, AI-008, AI-005 |

#### trips

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `GET /v1/trips` | 4 | bearer | — | read |  | TRIP-001 |
| `POST /v1/trips` | 4 | bearer | required | write |  | TRIP-001, TRIP-002 |
| `GET /v1/trips/{tripId}` | 4 | bearer | — | read |  | TRIP-003, OFF-001 |
| `PATCH /v1/trips/{tripId}` | 4 | bearer | — | write |  | TRIP-003 |
| `DELETE /v1/trips/{tripId}` | 4 | bearer | natural | write |  | TRIP-003 |
| `POST /v1/trips/{tripId}/days` | 4 | bearer | — | write |  | TRIP-004 |
| `PATCH /v1/trips/{tripId}/days/{dayId}` | 4 | bearer | — | write |  | TRIP-004 |
| `DELETE /v1/trips/{tripId}/days/{dayId}` | 4 | bearer | natural | write |  | TRIP-004 |
| `POST /v1/trips/{tripId}/days/{dayId}/items` | 4 | bearer | — | write |  | TRIP-005 |
| `PATCH /v1/trips/{tripId}/items/{itemId}` | 4 | bearer | — | write |  | TRIP-005 |
| `DELETE /v1/trips/{tripId}/items/{itemId}` | 4 | bearer | natural | write |  | TRIP-005 |
| `POST /v1/trips/{tripId}/sync` | 4 | bearer | required | write |  | TRIP-004, OFF-002 |
| `POST /v1/trips/{tripId}/apply-itinerary` | 4 | bearer | — | write |  | AI-009, TRIP-006 |
| `GET /v1/users/me/saved-places` | 4 | bearer | — | read |  | TRIP-003 |
| `PUT /v1/users/me/saved-places/{placeId}` | 4 | bearer | natural | write |  | TRIP-003 |
| `DELETE /v1/users/me/saved-places/{placeId}` | 4 | bearer | natural | write |  | TRIP-003 |

#### guides

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `GET /v1/destinations/{destinationId}/guides` | 4 | optional | — | read |  | GUIDE-001 |
| `GET /v1/guides/{guideId}` | 4 | optional | — | read |  | GUIDE-002, GUIDE-004, GUIDE-006 |
| `GET /v1/destinations/{destinationId}/audio-tours` | 4 | optional | — | read |  | GUIDE-005 |
| `GET /v1/audio-tours/{tourId}` | 4 | bearer | — | read |  | GUIDE-005, GUIDE-004 |
| `GET /v1/destinations/{destinationId}/offline-packages` | 4 | bearer | — | read |  | OFF-001 |
| `POST /v1/offline-packages/{packageId}/licenses` | 4 | bearer | — | write |  | OFF-004, OFF-001 |
| `DELETE /v1/offline-packages/{packageId}/licenses/{licenseId}` | 4 | bearer | natural | write |  | OFF-001 |
| `GET /v1/offline-packages/{packageId}/manifest` | 4 | bearer | — | read |  | OFF-001 |
| `GET /v1/users/me/offline-packages` | 4 | bearer | — | read |  | OFF-001 |

#### billing

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `GET /v1/billing/products` | 3 | optional | — | read |  | BILL-001 |
| `GET /v1/billing/entitlements` | 3 | bearer | — | read |  | BILL-002, BILL-003, BILL-007 |
| `POST /v1/billing/purchases/verify` | 3 | bearer | required | billing |  | BILL-004, BILL-005, BILL-003, BILL-007 |
| `POST /v1/billing/purchases/restore` | 3 | bearer | required | billing |  | BILL-006 |
| `POST /v1/billing/checkout-sessions` | 3 | bearer | required | billing |  | BILL-002, BILL-003 |
| `POST /v1/billing/portal-sessions` | 3 | bearer | — | billing |  | BILL-005 |
| `POST /v1/billing/webhooks/apple` | 3 | signature | — | webhook |  | BILL-007, BILL-008 |
| `POST /v1/billing/webhooks/google` | 3 | Pub/Sub OIDC | — | webhook |  | BILL-007, BILL-008 |
| `POST /v1/billing/webhooks/stripe` | 3 | signature | — | webhook |  | BILL-007, BILL-008, BILL-006 |

#### notifications

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `GET /v1/notifications` | 1 | bearer | — | read |  | NOTIF-001 |
| `GET /v1/notifications/unread-count` | 1 | bearer | — | read |  | NOTIF-001 |
| `POST /v1/notifications/read` | 1 | bearer | — | write |  | NOTIF-001 |
| `POST /v1/users/me/devices` | 1 | bearer | — | write |  | NOTIF-002, NOTIF-005 |
| `DELETE /v1/users/me/devices/{deviceTokenId}` | 1 | bearer | natural | write |  | NOTIF-002 |

#### admin

| Endpoint | Phase | Auth | Idempotency | Rate class | Entitlement | Requirements |
|---|---|---|---|---|---|---|
| `GET /v1/admin/reports` | 1 | bearer + `moderation.reports.read` | — | admin |  | ADM-001, SAFE-003, ADM-007, ADM-008 |
| `GET /v1/admin/reports/{reportId}` | 1 | bearer + `moderation.reports.read` | — | admin |  | ADM-001, ADM-002, SAFE-007, ADM-007, ADM-008, ADM-009 |
| `POST /v1/admin/reports/{reportId}/assign` | 1 | bearer + `moderation.reports.manage` | — | admin |  | ADM-001, ADM-007, ADM-008, ADM-009 |
| `POST /v1/admin/reports/{reportId}/resolve` | 1 | bearer + `moderation.reports.manage` | — | admin |  | ADM-002, ADM-007, ADM-008, ADM-009 |
| `GET /v1/admin/moderation-actions` | 1 | bearer + `moderation.actions.read` | — | admin |  | ADM-003, ADM-007, ADM-008 |
| `POST /v1/admin/moderation-actions` | 1 | bearer + `moderation.actions.write` | required | admin |  | ADM-003, ADM-002, ADM-007, ADM-008, ADM-009 |
| `GET /v1/admin/users/{userId}` | 1 | bearer + `users.read` | — | admin |  | ADM-003, ADM-007, ADM-008, ADM-009 |
| `POST /v1/admin/users/{userId}/suspend` | 1 | bearer + `users.suspend` | — | admin |  | ADM-002, ADM-007, ADM-008, ADM-009 |
| `POST /v1/admin/users/{userId}/reinstate` | 1 | bearer + `users.suspend` | — | admin |  | ADM-002, ADM-007, ADM-008, ADM-009 |
| `PATCH /v1/admin/destinations/{destinationId}` | 1 | bearer + `content.destinations.write` | — | admin |  | DEST-004, DEST-007, ADM-007, ADM-008, ADM-009 |
| `GET /v1/admin/safety/message-filter` | 2 | bearer + `safety.filters.manage` | — | admin |  | SAFE-006, ADM-007 |
| `PUT /v1/admin/safety/message-filter` | 2 | bearer + `safety.filters.manage` | — | admin |  | SAFE-006, ADM-007, ADM-008 |
| `POST /v1/admin/media/{mediaId}/rights` | 1 | bearer + `content.destinations.write` | — | admin |  | DEST-007, ADM-007, ADM-008, ADM-009 |
| `POST /v1/admin/challenge-rewards/{rewardId}/review` | 5 | bearer + `content.rewards.review` | — | admin |  | CHAL-014, ADM-007, ADM-008, ADM-009 |
| `GET /v1/admin/audit-logs` | 6 | bearer + `audit.read` | — | admin |  | ADM-002, SAFE-007, ADM-007, ADM-008 |

## 3. Authorization rules by resource family

Every rule is enforced server-side in the owning module's policy functions ([architecture §9](02-system-architecture.md#9-authorization-model)). "404 instead of 403" applies wherever revealing existence would leak information.

| Family | Who may read | Who may mutate | Notes |
|---|---|---|---|
| **Account (`/users/me/*`)** | Self | Self | Admins use separate `/v1/admin/users/*` endpoints, which are audited. Sessions list never shows IPs or tokens. |
| **Profiles** | Any authenticated user, unless either party blocked the other (404). Private accounts and `profile_visibility = connections` return `is_restricted = true` with reduced fields. | Self | `PublicProfile` is a distinct schema with **no** email, birth data, coordinates, distance, last-seen or session data, enforced by the contract privacy lint. |
| **Destinations / places** | Everyone (anonymous allowed). `resolve` and `places/nearby` need auth because they take a device point. | Platform admins (`content.destinations.write`) | Device points are request-scoped and never persisted or logged. |
| **Feed** | Authenticated: ranked feed. Anonymous: `/v1/public/posts` (public plus approved only, capped at 3 pages). | — | Relevance comes from **post destination metadata only**. Visibility, blocks and moderation are filtered in SQL. |
| **Posts / comments** | Per `visibility` (`public`, `followers`, `connections`, `private`) and blocks (bidirectional). `removed` content is visible to its author with a notice. | Author edits and deletes. Post author may delete comments on their post. Moderators via admin endpoints. | Media must be owned by the caller and have `purpose = post`. |
| **Follows** | Followers/following lists hidden for private accounts unless the viewer follows them. | Self | Following a private account creates a request. |
| **Blocks / reports** | Self (own blocks only) | Self | A block is immediate and bidirectional, and cascades (see `PUT /v1/users/{id}/block`). The blocked user is not notified. |
| **Media** | Owner (asset status). Rendered media follow the parent resource's rules. Private media use signed URLs only. | Owner | Quarantine, then scan, metadata strip, and promotion. |
| **Discovery** | Caller must be opted in (`discovery_enabled` + consent) **and** visible (an active visible session or a shared upcoming destination). Results exclude blocked users and invisible users. | Self (own session) | Destination-scoped only. No coordinates, distances or timestamps in results. |
| **Connections** | Parties to the request or connection | Requester creates and cancels. Recipient accepts and declines. Either party removes. | `connection_requests_from` and blocks produce a single generic `connection_request_not_allowed`. Cooldown applies after a decline. |
| **Conversations / messages** | Active members only. Group members see history from `joined_at_seq` per `new_member_history`. | Send: member, not restricted, not blocked (direct), connected (direct), and `chat_mode` allows. Edit: sender within the window. Delete: sender, or a group moderator with `messages.remove`. | Re-checked on **every** send, REST or realtime. Shared group membership does **not** authorize direct messages. |
| **Groups** | Members. Private groups return 404 to non-members. Invitation previews show a minimal `GroupSummary`. | By group permission (table below). Premium features also require `premium_features_active`. | Joining never requires a subscription. |
| **Challenges** | Group members see the member view (no answers, released hints only). `challenges.manage` sees the manager view. `challenges.judge` reads answers through a dedicated audited endpoint. | `challenges.manage` (create/edit/publish/cancel; also needs `challenges.create` on the group). `challenges.judge` (judge, winners, disputes, fulfillments). Members submit. | Submissions are append-only and transactional. Team mode accepts only the captain's submissions. |
| **Trips** | Owner, collaborators, and per `visibility` | Owner and editors | `If-Match` on every mutation. Offline sync via `/sync`. |
| **Guides / offline** | Everyone sees listings. Content and manifests are gated by tier and entitlement. | Platform content admins (admin API in a later phase) | Licenses are per device and count against `offline.packages`. |
| **Billing** | Self (`entitlements`, products are public) | Self (verify, restore, checkout, portal). Webhooks are provider-authenticated. | Client-asserted subscription status is **never** trusted. |
| **Admin** | Platform roles with the named permission (`x-platform-permission`) | Same | Every admin read of evidence, PII or answers, and every admin mutation, is written to `audit_logs`. |

### 3.1 Group permissions (system roles)

| Permission | owner | admin | moderator | member | Needs `premium_features_active` |
|---|:-:|:-:|:-:|:-:|:-:|
| `group.edit` | ✓ | ✓ | | | no |
| `group.delete` (archive) | ✓ | | | | no |
| `group.transfer` | ✓ | | | | no (allowed after lapse, per policy) |
| `members.invite` | ✓ | ✓ | ✓ if `members_can_invite` | ✓ if `members_can_invite` | **yes** |
| `members.approve` | ✓ | ✓ | ✓ | | **yes** |
| `members.remove` | ✓ | ✓ | ✓ (members only) | | no (safety) |
| `members.restrict` | ✓ | ✓ | ✓ (members only) | | no (safety) |
| `roles.assign` | ✓ | ✓ (below own rank) | | | no |
| `messages.remove` | ✓ | ✓ | ✓ | | no (safety) |
| `messages.pin` | ✓ | ✓ | ✓ | | no |
| `announcements.post` | ✓ | ✓ | | | no |
| `challenges.manage` | ✓ | ✓ | | | **yes** (also `challenges.create`) |
| `challenges.judge` | ✓ | ✓ | ✓ | | no (judging an existing challenge must stay possible after a lapse) |

Safety and moderation permissions are **never** paywalled. Rank rule: an actor can only act on members of strictly lower rank, and can only assign roles below their own rank. `MyGroupMembership.permissions` returns the *effective* set after these rules are applied.

---

## 4. Endpoint notes (non-obvious behaviour)

* **`GET /v1/feed`**: the `context` object reports which step of the PRD FEED-001 fallback chain produced the page: `gps` (from `near`), `selected` (explicit `destination_id` or browse destination), `upcoming_trip`, `interests`, `global`, or `following`. `radius_km` is set only for `nearby`. Pages come from a 15-minute ranked snapshot. `page.reset = true` means "replace, don't append".
* **`PUT /v1/users/me/discovery-location`**: send a destination, or a GPS point that the server resolves to city (and neighborhood) and then **discards**. The response contains destinations only.
* **`GET /v1/destinations/lookup?path=brazil/rio-de-janeiro`**: SEO slug-path lookup for the web. Segments are language-neutral and unique among siblings.
* **`POST /v1/posts/{id}/reactions`**: idempotent upsert. One reaction per user per post, and a different value replaces it. Remove it with `DELETE /v1/posts/{id}/reactions/me`. There are no per-kind reaction paths.
* **`PUT|DELETE /v1/posts/{id}/bookmark`**: idempotent.
* **`POST /v1/users/me/onboarding/complete`**: idempotent. Validates the mandatory fields and returns `Me`.
* **Messages**: REST `POST .../messages` and realtime `message.send` share one service path, so retries are safe under either. `200 + Idempotent-Replayed` signals a replay.
* **Group invitations**: link tokens are returned once and stored hashed. URLs carry the token in the fragment (`#t=`), and redemption and preview take it in a POST body, so tokens never appear in server logs. `invitation_invalid` deliberately does not distinguish unknown, expired, revoked and exhausted tokens.
* **AI**: generation is asynchronous (`202` + poll `GET /v1/ai/generations/{id}`, or wait for the `ai_generation_ready` notification). Output schemas have **no fields** for opening hours, prices, availability, live transit or safety claims.
* **Billing**: store purchases go through `purchases/verify` and `restore`. Web purchases go through Stripe `checkout-sessions` (relative `success_path` and `cancel_path` only, which prevents open redirects) and `portal-sessions`. The checkout success page **polls entitlements**. It never grants anything itself.

---

## 5. Rate-limit classes (initial values)

Limits are enforced per principal (user, or IP for anonymous) per class with a sliding window (Redis; PostgreSQL where no Redis exists, ADR-0021). The web BFF forwards the browser IP in `X-TB-Client-IP` with the shared `X-TB-Forwarding-Secret`; without the secret the header is ignored. Every response carries `RateLimit-Limit`, `RateLimit-Remaining` and `RateLimit-Reset`. Rejections are `429 rate_limited` with `Retry-After`. Values live in configuration and are tuned from production telemetry. Accounts younger than 7 days get **half** the `contact`, `message` and `media_upload` limits (anti-spam).

| Class | Limit (initial) | Scope | Fails when Redis is down |
|---|---|---|---|
| `none` | — | Health probes | — |
| `read` | 600 / min | user | open |
| `write` | 120 / min | user | open |
| `search` | 60 / min | user (anonymous: IP) | open |
| `guest` | 60 / min, plus a 3-page cap per cursor chain | IP | closed |
| `auth` | 10 / min per IP. 20 / h per IdP subject. Refresh: 60 / h per session | IP, subject, session | **closed** |
| `sensitive` | 10 / h (reports 20 / day, data export 2 / day, invitation preview/redeem 30 / h) | user | **closed** |
| `contact` | Connection requests 20 / day with a burst of 5 / min. Group invitations 50 / day. Join requests 20 / day | user | **closed** |
| `discovery` | 60 / min, 500 / day | user | **closed** |
| `message` | 30 / min sustained, burst 10 / 10 s. 20 / min per conversation | user | open (degraded) |
| `submission` | 10 / min per user, on top of per-challenge `max_attempts` and `attempt_cooldown_seconds` (enforced transactionally in Postgres, not Redis) | user | open (the DB still enforces attempts) |
| `media_upload` | 30 / h, 2 GB / day | user | closed |
| `ai` | 10 / h, on top of the monthly entitlement quotas | user | closed |
| `billing` | 20 / h | user | closed |
| `realtime_ticket` | 30 / min | session | closed |
| `webhook` | 1000 / min | provider (signature-verified first) | open |
| `admin` | 300 / min | admin user | open |

---

## 6. Error-code catalogue

All errors use `application/problem+json`. Clients must branch on `code`, never on `title` or `detail`, which are localized and may change. `feature_key` accompanies `entitlement_required`, `quota_exceeded` and `feature_disabled`.

| Code | HTTP | Meaning / client action |
|---|---|---|
| `bad_request` | 400 | Malformed request (bad JSON, failed webhook signature). |
| `validation_failed` | 422 | Body or parameters failed validation. See `errors[] {field, code, message}`. |
| `unauthenticated` | 401 | Missing or invalid credentials. Sign in. |
| `invalid_cursor` | 400 | Cursor is tampered, expired or from another listing. Restart the listing without a cursor. |
| `method_not_allowed` | 405 | HTTP method not supported on this path. |
| `email_unverified` | 403 | Action needs a verified email (AUTH-004). Prompt verification. |
| `mfa_required` | 403 | Staff route needs an MFA sign-in (ADM-007). Re-authenticate with MFA. |
| `reauthentication_required` | 401 | Staff session idle (30 min) or absolute (12 h) limit reached on admin routes (ADM-008). Sign in again. |
| `justification_required` | 400 | `X-Audit-Justification` missing or blank on an admin mutation or sensitive read (ADM-009). |
| `token_expired` | 401 | Access token expired. Refresh and retry once. |
| `token_invalid` | 401 | Token malformed, wrong issuer or audience, or an unknown refresh token. Sign in again. |
| `refresh_token_reused` | 401 | A rotated refresh token was reused outside the 30 s leeway. The family is revoked. Sign in again. |
| `session_revoked` | 401 | Session revoked (logout elsewhere, admin action). Sign in again. |
| `account_suspended` | 403 | Account suspended. Show the suspension notice. |
| `account_restricted` | 403 | A moderation restriction blocks this action (e.g. `posting_limited`). Explain it with `Me.account.restrictions` (SAFE-013). |
| `forbidden` | 403 | Authenticated but not permitted (non-entitlement reason). |
| `entitlement_required` | 403 | Premium needed (for groups, the owner's premium). Show an upsell when appropriate. |
| `feature_disabled` | 403 | Feature flag off for this user, region or app version. |
| `age_restricted` | 403 | Below the minimum age for the platform or feature. |
| `consent_required` | 403 | A consent (e.g. `traveler_discovery`, `ai_personalization`) must be granted first. |
| `discovery_disabled` | 403 | The caller is not opted in or not visible for discovery. |
| `connection_required` | 403 | Direct messaging needs an accepted connection. |
| `connection_request_not_allowed` | 403 | The recipient's settings or a block prevent the request. Deliberately generic. |
| `member_restricted` | 403 | Temporarily restricted in this group. |
| `chat_admins_only` | 403 | The group chat is in admin-only mode. |
| `message_edit_window_expired` | 403 | Edit window (15 min) elapsed. |
| `not_team_captain` | 403 | Only the team captain may submit. |
| `invitation_not_allowed` | 403 | A block prevents inviting this user. Deliberately generic. |
| `not_found` | 404 | Does not exist **or is not visible to you**. |
| `conflict` | 409 | State conflict (duplicate pending request, wrong state, already exists). |
| `already_connected` | 409 | Already connected. |
| `connection_request_cooldown` | 409 | Re-request blocked after a decline (default 30 days). |
| `idempotency_key_reused` | 409 | Same `Idempotency-Key`, different body. Generate a new key. |
| `idempotency_key_in_progress` | 409 | The original request is still processing. Retry after a short delay. |
| `quota_exceeded` | 409 | A quota (`groups.owned`, `ai.*`, `offline.packages`) is exhausted. See `feature_key` and entitlements. |
| `group_capacity_reached` | 409 | The group is full. |
| `owner_must_transfer` | 409 | The owner must transfer ownership before leaving. |
| `invitation_invalid` | 409 | Invitation unknown, expired, revoked or exhausted (indistinguishable on purpose). |
| `challenge_not_active` | 409 | Outside the challenge window, or not active. |
| `challenge_locked` | 409 | Rules cannot change after activation (except extending `ends_at`). |
| `attempts_exhausted` | 409 | No attempts left. |
| `attempt_cooldown` | 409 | Cooldown between attempts. See `Retry-After`. |
| `purchase_already_linked` | 409 | The store transaction belongs to another account. |
| `precondition_failed` | 412 | `If-Match` is stale. Refetch, merge, retry. |
| `payload_too_large` | 413 | Exceeds the size limit for the purpose. |
| `unsupported_media_type` | 415 | MIME type not allowed for the purpose. |
| `location_unresolvable` | 422 | The point is not inside any known destination. Ask the user to pick one. |
| `reward_not_permitted` | 422 | Prize type or description not allowed (cash, cash-equivalent, paid entry, random draw). |
| `purchase_invalid` | 422 | The store or provider rejected verification. |
| `media_not_ready` | 422 | Referenced media is still processing where readiness is required. |
| `media_rejected` | 422 | Referenced media failed scanning or policy. |
| `precondition_required` | 428 | `If-Match` header missing. |
| `rate_limited` | 429 | Slow down. See `Retry-After`. |
| `internal_error` | 500 | Unexpected error. Report `request_id`. |
| `upstream_unavailable` | 503 | A provider (IdP, store, maps) is unavailable. Retry with backoff. |
| `ai_unavailable` | 503 | The AI provider is unavailable or the circuit breaker is open. |
| `ai_output_invalid` | 502 | AI output failed schema or semantic validation after the repair retry. Safe to retry. |
| `service_unavailable` | 503 | Platform degraded or in maintenance. Retry with backoff. |

### 6.1 Reserved codes (never emitted by the backend)

These codes are reserved so that client-side error handling can share the `ErrorCode` space without collisions. They are listed under `x-reserved-codes` on the `ErrorCode` schema. The backend must never emit them, and a CI test asserts they are absent from the backend's error enum.

| Code | Emitted by | Meaning |
|---|---|---|
| `csrf_failed` | Web BFF | ADR-001 |
| `network_error` | Any client, locally | The request never got an HTTP response (offline, DNS, TLS, timeout). |
| `feature_not_available_in_mock` | Web mock adapters only | ADR-001 |

---

## 7. Media upload limits by purpose

| Purpose | Allowed types | Max size | Max per parent |
|---|---|---|---|
| `post` | JPEG, PNG, WebP, HEIC. MP4 / QuickTime (≤ 60 s at launch, contract max 180 s) | 25 MB image, 200 MB video | 10 per post |
| `avatar` | JPEG, PNG, WebP, HEIC | 10 MB | 1 |
| `message` | JPEG, PNG, WebP, HEIC | 25 MB | 10 per message |
| `group_cover` | JPEG, PNG, WebP | 10 MB | 1 |
| `challenge` | JPEG, PNG, WebP | 10 MB | 1 |

The server checks declared values against actual values (magic bytes, size, sha256) at finalize time. EXIF and GPS metadata are stripped from every image and video before it becomes `ready`.

---

## 8. Worked examples

### 8.1 Rio de Janeiro feed

A UK traveler opens the app in Rio with location permission. The client sends the device point, which the server resolves to Rio and discards.

```http
GET /v1/feed?tab=for_you&near=-22.9711,-43.1822&limit=2 HTTP/1.1
Authorization: Bearer eyJhbGciOiJFZERTQSIsImtpZCI6ImsxIn0...
Accept-Language: en-GB
X-Request-ID: 7b0c2c1e-mobile-ios-000123
```

```http
HTTP/1.1 200 OK
Content-Type: application/json
X-Request-ID: 7b0c2c1e-mobile-ios-000123
RateLimit-Limit: 600
RateLimit-Remaining: 597
RateLimit-Reset: 41
```

```json
{
  "data": [
    {
      "id": "0193a7f2-6c1e-7b44-9d0a-3c5e8f1a2b01",
      "author": { "id": "0192f1aa-1111-7000-8000-000000000001", "handle": "lucia.travels", "display_name": "Lucía", "avatar": null },
      "kind": "attraction_recommendation",
      "body": "Sunset at Arpoador is unmissable. Get there 40 minutes early.",
      "language": "en",
      "visibility": "public",
      "location_precision": "place",
      "primary_destination": { "id": "0190c0de-0000-7000-8000-00000000c0aa", "kind": "neighborhood", "slug": "ipanema-rio-de-janeiro-br", "path": "brazil/rio-de-janeiro/ipanema", "name": "Ipanema", "country_code": "BR" },
      "place": { "id": "0190c0de-0000-7000-8000-0000000p1ace", "name": "Pedra do Arpoador", "category": "viewpoint", "destination_id": "0190c0de-0000-7000-8000-00000000c0aa", "location": { "lat": -22.9893, "lng": -43.1915 } },
      "travel_date": "2026-11-02",
      "rating": null,
      "trip_id": null,
      "tags": ["sunset", "beach"],
      "media": [ { "id": "0193a7f2-aaaa-7000-8000-000000000m01", "kind": "image", "status": "ready", "url": "https://cdn.travelbuddy.example/m/0193a7f2-aaaa/w1080.webp", "url_expires_at": null, "width": 1080, "height": 1350, "duration_ms": null, "alt_text": "Crowd watching the sunset from the rock", "blurhash": "LKO2?U%2Tw=w]~RBVZRi};RPxuwH", "variants": {} } ],
      "published_at": "2026-11-03T21:14:09Z",
      "edited_at": null,
      "counts": { "reactions": 128, "comments": 14, "bookmarks": 37, "shares": 5, "reactions_by_type": { "like": 90, "love": 30, "helpful": 8 } },
      "viewer": { "reaction": null, "bookmarked": false, "is_author": false, "can_edit": false, "can_delete": false, "can_comment": true }
    }
  ],
  "page": { "next_cursor": "eyJzIjoiZnM6MDE5M2E3Li4uIiwibyI6Mn0.Hk3x9Q", "has_more": true, "reset": false },
  "context": {
    "destination": { "id": "0190c0de-0000-7000-8000-00000000r10a", "kind": "city", "slug": "rio-de-janeiro-br", "path": "brazil/rio-de-janeiro", "name": "Rio de Janeiro", "country_code": "BR" },
    "source": "gps",
    "radius_km": null
  }
}
```

Points to note:

* The post's author is not Brazilian and the viewer is from the UK. Relevance comes only from the post's destination (Ipanema, and its ancestor Rio). The author's nationality, residence or IP play no part.
* `context.source = gps`: the device point resolved to Rio. A user in London who selected Rio as their browse destination gets the same posts with `source = selected`.
* The place has coordinates because it is a **public place**. No user coordinates appear anywhere.

### 8.2 `entitlement_required` on group creation

A free user tries to create a group:

```http
POST /v1/groups HTTP/1.1
Authorization: Bearer eyJhbGciOiJFZERTQSIsImtpZCI6ImsxIn0...
Idempotency-Key: 5b8c7d0e-2f1a-4c39-9a51-0d6c2e7f8a90
Content-Type: application/json

{ "name": "Rio Adventure Crew", "primary_destination_id": "0190c0de-0000-7000-8000-00000000r10a",
  "start_date": "2026-12-10", "end_date": "2026-12-17", "visibility": "private",
  "interests": ["hiking", "food", "photography"] }
```

```http
HTTP/1.1 403 Forbidden
Content-Type: application/problem+json
X-Request-ID: 01JC8ZQ4M6V3K9T2R7B5N1D0XE
```

```json
{
  "type": "https://docs.travelbuddy.example/errors/entitlement_required",
  "title": "Premium membership required",
  "status": 403,
  "detail": "Creating travel groups requires an active Premium membership.",
  "instance": "/v1/groups",
  "code": "entitlement_required",
  "feature_key": "groups.create",
  "request_id": "01JC8ZQ4M6V3K9T2R7B5N1D0XE"
}
```

The check runs server-side against `billing.service.has(user, "groups.create")`, and nothing the client asserts can change the outcome. A retry with the same `Idempotency-Key` after purchasing would replay this 403. The client must use a **new** key after the entitlement changes, because idempotency records the first outcome.

---

## 9. Versioning and deprecation policy

1. **Additive changes in place.** New endpoints, new optional request fields, new response fields and new enum values in *response-only* enums ship without a version bump. Clients must ignore unknown fields and treat unknown enum values as "other". This is part of the client contract and is tested in client CI.
2. **Breaking changes require `/v2`**, scoped to the affected resource family where possible. Breaking means removing or renaming a field or endpoint, tightening validation, changing semantics or status codes, adding a required request field, or adding a value to a *request* enum that older servers would reject.
3. **Detection.** CI runs a breaking-change diff (`oasdiff breaking`) of every contract change against `main`. A breaking change fails the build unless the PR is labelled `api-breaking` and carries an approved ADR.
4. **Deprecation signalling.** Deprecated operations are marked `deprecated: true` in the contract and respond with `Deprecation` (RFC 9745) and `Sunset` (RFC 8594) headers plus a `Link: <docs>; rel="deprecation"`.
5. **Support window.** At least **6 months** after a replacement ships, because mobile clients upgrade slowly. Retirement is coordinated with `GET /v1/client-config` (`min_supported_version`, `update_required`), which can force an upgrade.
6. **Dev-only operations** (`x-dev-only`) are not part of the public compatibility promise and do not exist in staging or production.
7. **Contract versioning.** `info.version` follows SemVer for the *document*: patch = clarifications, minor = additive, major = new API version. Each release is tagged `contracts-vX.Y.Z`.
