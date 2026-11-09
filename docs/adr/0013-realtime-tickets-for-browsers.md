# ADR-0013 — Single-use realtime tickets for browser WebSocket authentication

* **Status:** Accepted (backend endpoint required)
* **Date:** 2026-11-09
* **Related:** [doc 02 §12](../02-system-architecture.md#12-realtime), [06 — Realtime protocol](../06-realtime-messaging-protocol.md), [ADR-0011](0011-web-bff-cookie-sessions.md)

## Context

The realtime gateway authenticates with the access token in the first `auth` frame. Under ADR-0011, browser JavaScript cannot read the access token.

## Decision

* A new endpoint, `POST /v1/realtime/tickets` (Bearer), returns `{ticket, expires_at}`. The ticket is a 256-bit random value stored hashed in Redis, with a **TTL of 30 s, single use**, and bound to `user_id` and `session_id`.
* The browser obtains a ticket through the BFF (`POST /api/realtime/ticket`, CSRF-protected) and sends the standard envelope `{"v":1,"type":"auth","id":"…","ts":"…","data":{"ticket":"…"}}` as the first frame (contract: `contracts/realtime/*.schema.json`). `data` carries **exactly one** of `access_token` (mobile) or `ticket` (web). The gateway builds the same `Principal` either way.
* **Re-authentication:** when the server sends `auth.expiring`, a web connection must send a new `auth` frame on the same socket within the grace period, using a fresh ticket. Web connections therefore re-authenticate about every 15 minutes, matching the access-token lifetime. If the client fails to re-authenticate, the server closes the socket and the client reconnects normally.
* Session revocation pushes `session.revoked` and closes sockets, as today.
* The gateway checks the WebSocket `Origin` header against an allow-list of web origins.

## Consequences

* Tickets never appear in URLs, so they never land in access logs.
* Each reconnect costs one BFF round-trip, which is acceptable given backoff.
