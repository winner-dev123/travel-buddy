# ADR-0020: Supabase Auth as the managed identity provider

- **Status:** Superseded by [ADR-0028](0028-firebase-platform-and-railway-hosting.md) (cutover pending; in force until then)
- **Date:** 2026-11-09
- **Deciders:** Product owner (delegated the recommendation: "pls recommend you and continue"), backend
- **Requirements:** AUTH-001..007, ADM-007, ADM-008, SAFE-010
- **Resolves:** PRD Q-1 (IdP vendor)
- **Amends:** [ADR-0003](0003-oidc-idp-with-platform-sessions.md) (vendor choice), [ADR-0018](0018-supabase-managed-postgres.md) (publishable-key rule)

## Context

ADR-0003 delegates credentials and federation to a managed OIDC identity provider and leaves the vendor open (Q-1). The database already runs on Supabase (ADR-0018), and staging already trusts Supabase Auth tokens (ADR-0019): ES256 tokens verified against the project's JWKS, issuer `https://dmvhbgxxxilcniadoqvb.supabase.co/auth/v1`, audience `authenticated`.

Supabase Auth offers email/password with confirmation, Google, Apple, TOTP MFA (`aal2`), CAPTCHA and rate limits. It is included in the plan we already pay for, so there is no extra vendor contract or data processor.

Supabase Auth is **not** a classic confidential OIDC client/server pair. Clients call its REST endpoints (`/auth/v1/authorize`, `/auth/v1/token?grant_type=pkce|password`) with the project's **publishable key** (`sb_publishable_…`, formerly the anon key). ADR-0018 said "our clients do not use the anon key". That rule existed to keep the Data API unreachable, and it has to be refined rather than ignored.

## Decision

* **Supabase Auth is the identity provider.** Sign-in methods: email and password (confirmation required), Google, and Sign in with Apple (required on iOS when Google is offered). The backend keeps ADR-0003 unchanged. It verifies the Supabase access token like any OIDC ID token, by `iss`, signature (ES256 via JWKS; never the legacy HS256 secret), `aud` and expiry. It then issues its own platform session, so revocation, device lists and WebSocket auth stay ours.
* **Publishable key, Auth only.** The publishable key may ship in the web BFF (server-side environment variable) and in the mobile app, **only to call Supabase Auth endpoints**. It is a public identifier, not a secret. Every other surface it could reach is closed:
  * Data API: disabled, plus RLS deny-all and revoked `anon`/`authenticated` privileges (ADR-0018, unchanged).
  * Realtime: **private channels only** ("Allow public access to channels" off). Our realtime gateway (doc 06) does not use Supabase Realtime.
  * Storage: no buckets and no storage policies. Media uses our own storage plan.
  * Edge Functions: none deployed.
  * The `service_role` / secret keys are never distributed to clients. The backend gets one only when account deletion needs the Auth Admin API (see Consequences), as a server-side secret.
* **Flows:**
  * Web (ADR-0011 BFF): Authorization Code with **PKCE**, run server-side. The BFF exchanges the code for a Supabase access token, then calls `POST /v1/auth/login` (or `/register`) with it as `id_token`. The browser never holds Supabase or platform tokens. Redirect URI: `https://<web origin>/api/auth/callback`.
  * Mobile: PKCE through the system browser (`travelbuddy://auth/callback`). Native Google and Apple ID tokens can go through Supabase `signInWithIdToken` with a `nonce`. The app then exchanges the Supabase access token for a platform session and stores only platform tokens in secure storage.
  * The Supabase session is used once, for the exchange. Clients sign out of Supabase after logout and do not refresh Supabase tokens to call our API.
* **Redirect allow-list:** exact URLs only (no `https://*.vercel.app`-style wildcards, which would let any Vercel app receive auth codes). Site URL is the public web origin.
* **Staff MFA (ADM-007):** Supabase puts `aal: "aal2"` in tokens issued after a TOTP challenge. The verifier maps `aal2` to the RFC 8176 `mfa` method in the session's `amr`. Platform authorization denies staff permissions with `403 mfa_required` when `mfa` is absent. Because `amr` is copied at login, a staff member who enrols MFA must sign in again.
* **Anonymous sign-ins stay disabled** in Supabase. The verifier also rejects tokens with `is_anonymous: true`.
* **Age gate and consent stay in our registration** (`POST /v1/auth/register`). A Supabase Auth user without a platform account has no access to anything.

## Consequences

* No extra vendor. Identity data lives in the same Supabase project and region as the database, so the SAFE-010 transfer assessment covers both.
* **Lock-in is contained.** The backend only knows issuer/JWKS/audience (configuration). `authentication_identities (issuer, subject)` allows migrating users to another IdP later by linking a new issuer.
* **Abuse of public Auth endpoints** (sign-up spam, credential stuffing) is handled by Supabase rate limits now. **Before public launch:** enable CAPTCHA (Attack Protection: Cloudflare Turnstile or hCaptcha) and leaked-password protection (Pro plan).
* **Account deletion (PROF/SAFE requirements)** must also delete the Supabase Auth user. That needs the Auth Admin API with a secret key held only by the backend worker. This is tracked with the deletion workflow.
* **Email deliverability:** Supabase's built-in SMTP is rate-limited and meant for development. Configure a custom SMTP sender before real users.
* The ADR-0018 statement "our clients do not use the anon key" is superseded by the publishable-key rule above. Threat T-OPS-08 gains the Realtime and Storage controls.
* Supabase access tokens default to a 1 h lifetime. That does not matter here, because they are exchanged once and never used as API bearer tokens.

## Alternatives considered

* **Auth0 / Cognito / Firebase / Ory / Keycloak (ADR-0003 candidates):** all viable and standard OIDC. They add a vendor, a DPA and cost, or (Keycloak) hosting. The backend abstraction keeps them as a future option.
* **Supabase "OAuth Server" (beta), making Supabase a full OIDC provider for a confidential web client:** it is meant for third-party apps and would need our own consent UI, and it is beta. Not chosen.
* **Calling Supabase Auth from the browser with supabase-js:** it would put Supabase sessions in browser storage, against the ADR-0011 BFF cookie model. Not chosen for web.
