# ADR-0011 — Web sessions through a BFF with sealed HTTP-only cookies

* **Status:** Accepted (the backend changes listed below are required before production)
* **Date:** 2026-11-09
* **Related:** [doc 02 §8](../02-system-architecture.md#8-identity-and-sessions), [ADR-0003](0003-oidc-idp-with-platform-sessions.md)

## Context

Doc 02 issues platform sessions as a 15-minute JWT access token plus a rotating opaque refresh token with reuse detection, sent as `Authorization: Bearer`. Mobile stores them in the secure enclave. A browser has no equivalent: tokens in `localStorage` or JS memory are exposed to any XSS. The brief asks for HTTP-only cookies.

## Decision

The Next.js server acts as a **Backend-for-Frontend**:

1. **Login.** `/api/auth/login` starts OIDC Authorization Code + PKCE (S256) with `state` and `nonce`, stored in a short-lived sealed `tb_oidc` cookie (10 min, `SameSite=Lax`, path `/api/auth`). `/api/auth/callback` validates `state`, exchanges the code as a confidential client, and posts the ID token to `POST /v1/auth/login` (or `/register`) with `client: "web"`.
2. **Storage.** The platform tokens go into one cookie, `tb_session`, encrypted with JWE (`dir` + `A256GCM`) using a 256-bit key derived from `SESSION_SECRET`. Attributes: `HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=<refresh lifetime>`. The payload is `{at, at_exp, rt, uid, sid, roles}`. Browser JavaScript can never read or replay the tokens.
3. **Use.** Server Components call the platform directly with Bearer. Browser code calls `/api/v1/*`, which unseals the cookie and forwards the call with Bearer, `Accept-Language` and `X-Request-ID`. The proxy allow-lists methods and strips hop-by-hop and cookie headers.
4. **Refresh.** `proxy.ts` refreshes during navigation when fewer than 60 s remain, and rewrites both the forwarded request cookie and the response cookie. The BFF proxy refreshes on demand when it sees an expired token or a `401 token_expired`.
5. **CSRF.** `SameSite=Lax` plus a double-submit token: a random `tb_csrf` cookie (not HttpOnly, `SameSite=Strict`) is echoed in `X-CSRF-Token` and compared in constant time on every non-safe BFF request. An `Origin` / `Sec-Fetch-Site: same-origin` check also applies.
6. **Logout.** `POST /api/auth/logout` (CSRF-protected) calls `POST /v1/auth/logout`, clears cookies, and optionally redirects to the IdP end-session endpoint.
7. **Session fixation.** Every login writes a brand-new `tb_session` and rotates `tb_csrf`.

## Required backend changes (doc 02 amendments)

* `POST /v1/auth/login|register` accept `client: "web"` and record it on `user_sessions`, so session lists can show "Web — Chrome on macOS".
* **Refresh reuse leeway:** presenting the immediately previous refresh token within **30 s** of its rotation returns the *same* successor pair instead of revoking the family. Without this, two parallel browser requests that both refresh would log the user out. Reuse after the leeway still revokes the family.
* `POST /v1/realtime/tickets` ([ADR-0013](0013-realtime-tickets-for-browsers.md)).

## Development identity

On the web side, `DevIdentityProvider` offers a persona picker at `/dev/login`. It is enabled only when `APP_ENV ∈ {development, test}`, and startup fails if it is configured anywhere else. It uses the backend's development-only dev IdP (doc 02 §8): `POST /v1/dev/idp/token {sub, email, name}` returns an EdDSA-signed ID token (`iss urn:travelbuddy:dev-idp`), which then goes through the normal `POST /v1/auth/login` / `register` path. Dev tokens are therefore checked by the same OIDC verifier as production.

## Consequences

* The web server holds credentials in transit, so it must run on trusted infrastructure, never on an untrusted edge.
* The cookie is about 1 KB, well under the 4 KB limit.
* Session revocation reaches the web at the next refresh (≤ 15 min), the same as mobile. Admin actions such as suspension also invalidate refresh tokens immediately.
