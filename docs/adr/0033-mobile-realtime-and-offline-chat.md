# ADR-0033: Realtime chat on mobile, PostgreSQL fanout, and an offline-first outbox

- **Status:** Accepted
- **Date:** 2026-11-12
- **Deciders:** Product owner (asked for fast, reliable delivery that keeps working on very poor networks, typing indicators, read receipts with avatars and instant friend-request notifications), backend/mobile
- **Requirements:** DM-003..008, DM-012, DM-014, DM-015, NOTIF-001, NOTIF-006, CONN-001, NFR-001
- **Amends:** [ADR-0023](0023-realtime-delivery-and-hosting.md) (adds the PostgreSQL bus; the app now uses the socket instead of polling only)

## Context

The app showed chats by polling every 4 s. A multi-emulator test on staging showed:
- a message took several seconds to reach the other person;
- a just-sent bubble could vanish until the next poll;
- nothing appeared when a friend request arrived while the app was open.

The WebSocket gateway of ADR-0023 has existed since Phase 3, and staging (Railway) is now a long-running process that can hold sockets. A live probe confirmed it: auth, typing, send with ack, and `message.new` all worked. Two gaps remained:

1. **Events from the worker reach no socket.** Without Redis, the bus is in-process. A notification is created by the background worker, a different process from the API that holds the sockets.
2. **Requests are slow because of geography.** Measured from a client over a kept-alive connection, a no-database request took about 0.4 s, but any database request took 2–4 s. The API ran in US West while the database (Supabase) is in US East, and every query crossed the continent.

## Decision

1. **PostgreSQL fanout.** `REALTIME_BUS=auto` now resolves to `postgres` outside development and test when there is no Redis, and to in-process memory behind a transaction pooler, which can't `LISTEN`.
   - `PostgresBus` delivers each event to the publishing process's own sockets at once, then sends it with `pg_notify` to the other processes. Each process listens on one held connection and ignores its own notifications.
   - Large recipient lists are split to stay under the 8 kB payload limit.
   - When the listening connection drops, the bus reconnects and tells every local socket to resync (`sync.required server_recovered`).
2. **`notification.new` frames.** The job that turns a domain event into notifications publishes each new one after its transaction commits. The gateway renders it for the receiving user exactly as `GET /v1/notifications` would, including block filtering. A friend request therefore shows up in the open app at once.
3. **The app keeps one socket while signed in and in the foreground** (docs/06 §5):
   - Connections: auth with the access token, re-auth on `auth.expiring`, and a heartbeat ping every 25 s.
   - Reconnects: jittered exponential backoff, plus an immediate reconnect when the network or the app comes back. Close codes are handled as docs/06 §9 says.
   - Catch-up: after `auth.ok`, the app sends `sync.request` with what it holds and refetches only the gaps.
   - Polling stays as a safety net: every 30 s while the socket is healthy, and every 4 s when it isn't.
4. **Offline-first sending.**
   - The outbox: a message goes into an outbox kept on the device and shows at once as "sending". The outbox sends over the socket and waits up to 10 s for the ack. Without a socket, it falls back to REST.
   - Retries: the same `client_message_id` is reused on every retry, so a send that reached the server is never duplicated (DM-005). Network failures retry with backoff and also wait for connectivity. A refusal (safety filter, restriction) marks the message "not sent" with the reason, and the user can retry or delete it.
   - History cache: the inbox and the last 30 conversations (newest 60 messages each) are kept on the device (`chat-cache.json`), restored at startup as stale data, so chats open without a network, even right after a restart.
   - Session: a launch whose token refresh fails only for lack of network keeps the traveller signed in with the last `Me` kept on the device; the API client refreshes before its first request and `Me` is reloaded once a connection is back. A refused or missing session signs out as before.
   - Wipe: the outbox, the chat cache and the saved `Me` are deleted whenever the session ends on the device (sign-out, revoked, expired or missing session), never on a network failure, so another account never sees or sends them (T-MSG-08).
5. **Typing and read receipts.** The app sends `typing.start` at most every 3 s while the draft is non-empty, and `typing.stop` on send, on an empty draft, or on leaving the chat. It shows "Name is typing…" from `typing` frames (8 s TTL). In direct chats, the reader's avatar shows next to "Read" under my newest message ("Sent" before it's read); read marks go over the socket when it is open.
7. **Chat comfort (DM-015).** The send button sits on the input's line, on the right by default or on the left for left-handed use, and the chat background is none, one of two built-in CC0 trip photos, or one of the traveller's own story photos copied into the app. Both are kept on the device (SCR-119).
6. **Hosting.** The API and the worker run in the database's region (Railway US East with Supabase us-east-1). This is configuration, done in the Railway dashboard (docs/11 §1.16).

## Consequences

- Messages, typing and receipts arrive in about one network round trip. Notifications arrive as soon as the worker has made them.
- The API holds one extra database connection per process, for `LISTEN`. Supabase's session pooler supports it, and the transaction pooler doesn't, so the bus falls back to memory there.
- Push still covers a closed app. It needs the Expo (EAS) project and FCM credentials (docs/14 §6).
- The REST fallback keeps everything working on networks or proxies that block WebSockets, at polling speed.

## Alternatives considered

- **Add Redis on Railway:** another paid service to run. PostgreSQL is already there and handles our event volume easily.
- **Long polling over HTTP:** it works through any proxy, but costs a held request per open chat. The gateway already exists, is specified and tested, and is the better fit; REST polling remains the fallback.
- **Server-sent events:** one-way only, so typing and sends would still need separate requests.
