# ADR-0021: Rate-limit counter stores and client IP trust

- **Status:** Accepted
- **Date:** 2026-11-09
- **Deciders:** Backend
- **Requirements:** SAFE-005, NFR-006, T-AUTH-11

## Context

docs/05 §5 defines rate-limit classes (per user, per IP or per key) enforced with a sliding window
"in Redis", with classes that fail open or closed when Redis is down. Staging runs the API on Vercel
serverless (ADR-0019) with no Redis, and production may start the same way. In-memory counters
don't work there: every invocation can land on a different instance.

The web reaches the API through its BFF (ADR-0011) from shared Vercel egress IPs. Per-IP classes
(`auth`, `guest`) would then count every web visitor as one client, which is the lock-out half of
T-AUTH-11.

## Decision

1. **One limiter, pluggable counter stores.** Each class has one or more limits. A *bucket* is a
   named variant: `reports` is 20/day instead of the `sensitive` default 10/h, `auth_subject` is
   20/h per IdP subject, `auth_refresh` is 60/h per session. The algorithm is a sliding-window
   counter over two fixed windows (`previous * (1 - elapsed/window) + current`). Rejected requests
   count too.
   - **Redis** (`INCR` + `EXPIRE` + `GET` in one pipeline) when `REDIS_URL` is set.
   - **PostgreSQL** otherwise: an UNLOGGED `rate_limit_counters` table, one
     `INSERT … ON CONFLICT … RETURNING` per limit in its own short transaction, with opportunistic
     pruning.
   - **Memory** in development. Rate limiting is **off** in tests, except in tests that inject a
     store.
   - `RATE_LIMIT_STORE=auto` picks the store from these rules. Staging and production refuse to
     boot with `memory` or `disabled`.
2. **Failure modes follow docs/05.** Fail-open classes let requests through when the store errors.
   Fail-closed classes (`auth`, `guest`, `sensitive`, `contact`, `discovery`, `media_upload`, `ai`,
   `billing`, `realtime_ticket`) return `503 service_unavailable` with `Retry-After: 5`.
3. **Classes live on routes.** `openapi_extra={"x-rate-limit-class": …}` is set via
   `rate_limited()`. Otherwise `/v1/admin/*` → `admin`, health and internal → `none`, `GET` →
   `read`, other methods → `write`. A contract test checks every implemented route against the
   contract's `x-rate-limit-class`. Enforcement is an app-wide dependency, so it runs before
   authentication and before any database work.
   - Keyed buckets apply where the key becomes known: the IdP subject after ID token verification,
     and the session behind a refresh token, checked inside the refresh transaction so a rejection
     rotates nothing.
4. **Client IP.**
   - The BFF forwards the browser IP in `X-TB-Client-IP`. It is trusted only together with
     `X-TB-Forwarding-Secret`, which must equal `CLIENT_IP_FORWARDING_SECRET` (≥ 32 chars; compared
     in constant time).
   - Otherwise `X-Real-IP` / `X-Forwarded-For` are used when `TRUST_PROXY_HEADERS` is on. It
     defaults to on when `VERCEL=1`, because Vercel sets and overwrites those headers.
   - Otherwise the socket peer is used.
   - IPv6 addresses count per /64.
5. **Headers.** `RateLimit-Limit`, `RateLimit-Remaining` and `RateLimit-Reset` (from the most
   restrictive limit) go on every response of a rate-limited route. A 429 also carries
   `Retry-After`.

## Consequences

- Staging enforces the documented limits today with no extra infrastructure. Adding Redis later is
  just setting `REDIS_URL`.
- With the PostgreSQL store, every rate-limited request costs one small UNLOGGED upsert on the
  primary. That is acceptable at staging and launch volumes; Redis is the scale path.
- UNLOGGED counters are lost on a database crash. That is harmless: limits briefly reset.
- Until the BFF sends the forwarding headers and the secret is set on both Vercel projects, the
  web's anonymous traffic shares one per-IP quota (`auth` 10/min, `guest` 60/min). Signed-in
  traffic is counted per user and is unaffected. Refresh is counted per session, not per IP.
- The 7-day half-limit for new accounts (`contact`, `message`, `media_upload`) lands with those
  modules: it needs the account age, which access tokens don't carry yet.

## Alternatives considered

- **Redis only (managed Upstash, etc.):** another vendor and secret before launch, for traffic
  PostgreSQL handles easily. Kept as the production scale path.
- **Edge or WAF rate limiting (Vercel Firewall):** coarse, per IP only, and can't express
  per-user, per-subject or per-session buckets. It may still sit in front as a flood shield.
- **Trusting `X-Forwarded-For` from anyone:** trivially spoofed to dodge per-IP limits.
