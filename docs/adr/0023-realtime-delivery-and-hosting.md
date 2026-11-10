# ADR-0023: Realtime delivery through per-user channels, with REST as the fallback

- **Status:** Accepted
- **Date:** 2026-11-09
- **Deciders:** Backend
- **Requirements:** DM-003, DM-004, DM-006..008, DM-012

## Context

docs/06 specifies the WebSocket protocol: frames, auth, acks, sync and limits. It assumes a
`realtime` process role behind a load balancer and Redis pub/sub channels per conversation
(`conv:{id}`) and per user (`user:{id}`). The staging API runs on Vercel serverless functions
(ADR-0019), which cannot hold WebSocket connections, and there is no Redis on staging. Messaging
(BL-3.03) already stores everything and serves history and gap sync over REST.

## Decision

1. **The gateway is part of the API application** (`/v1/realtime` in `app.main:app`). Any
   long-running ASGI host (uvicorn locally, a container, a VM) serves REST and WebSockets from the
   same code. A separate `realtime` deployment is the same entrypoint behind a WebSocket-capable
   load balancer; no second codebase is needed.
2. **One channel per user, not per conversation.** The messaging service publishes each event
   after its transaction commits, addressed to the users who should see it (`rt:user:{id}`). The
   membership decision is made by the publisher, so a member who leaves or is blocked simply stops
   receiving, and gateways need no subscription bookkeeping when membership changes. This
   replaces the `conv:{id}` channels in docs/06 §5.3 and §13.
3. **Events carry IDs, connections render.** `message.new` and `message.updated` events carry
   only the conversation and message IDs. Each connection loads the message as its own user sees
   it, with the same access checks as REST. This keeps per-viewer fields correct
   (`client_message_id` for the sender's devices, `reacted_by_me`) and re-checks access at delivery
   (docs/06 §12.2). Receipts are filtered by the publisher (reciprocal read receipts, delivery only
   in direct chats); typing never crosses a block.
4. **Bus adapters.** `MemoryBus` in a single process (development, tests, one gateway instance)
   and `RedisBus` (pub/sub) across processes. `REALTIME_BUS=auto` picks Redis when `REDIS_URL` is
   set outside development and test. Publishing is best effort and never fails a request: the
   database is the record, and clients catch up by `seq`.
5. **REST is the fallback.** Where WebSockets are unavailable (Vercel serverless, or a client
   whose socket keeps failing), clients poll `GET /v1/conversations` and
   `GET /v1/conversations/{id}/messages?after_seq=` while a chat is open, and rely on push
   notifications (BL-3.06) when backgrounded. Both paths run the same service, so behaviour is the
   same.

## Consequences

- Realtime on staging needs a long-running host plus Redis (for example a small container with a
  managed Redis), then `REALTIME_BUS=redis` on both the API and the gateway so REST-originated
  events reach sockets. Until then, mobile uses the REST fallback.
- Each delivered message costs one read per receiving connection. That is fine at v1 volumes. If
  it becomes hot, the publisher can include the rendered message and the connection can patch the
  per-viewer fields.
- Web tickets (ADR-0013) are implemented (BL-3.15) and stored hashed in PostgreSQL (no Redis
  needed). `notification.new` frames are not implemented yet.
