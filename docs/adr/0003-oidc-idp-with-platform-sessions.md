# ADR-0003: Managed OIDC identity provider + platform-issued sessions

- **Status:** Accepted (IdP vendor selection: Proposed, see PRD Q-1)
- **Date:** 2026-11-09
- **Requirements:** AUTH-001..007
- **Amended by:** [ADR-0011](0011-web-bff-cookie-sessions.md) (web BFF sessions, refresh reuse leeway)

## Context
We need email/password, Sign in with Apple, Google Sign-In, verification, password reset and multi-device sessions. Building credential storage ourselves is high-risk. We also need full control of sessions (revocation, WebSocket auth, device list) and portability between IdP vendors.

## Decision
* Credentials and federation are delegated to a managed **OIDC IdP** (candidates: Auth0, AWS Cognito, Firebase Authentication, Ory Network, Keycloak). The backend is configured with issuer, audience and JWKS URL only.
* The backend exchanges a verified IdP ID token for a **platform session**: an EdDSA-signed access JWT (15 min) plus an opaque, rotated refresh token (hash stored in `user_sessions`, reuse detection revokes the family, with a 30 s leeway for the immediately previous token per ADR-0011).
* `authentication_identities (issuer, subject)` maps IdP identities to users, so one user may link several methods and the IdP can be migrated.
* `DevIdentityProvider` exists for local and tests only, with a production boot guard.

## Consequences
* No passwords stored by us. IdP lock-in is limited to the sign-in UI and SDK.
* We own session security code (rotation, reuse detection), which needs careful testing (T-AUTH-02).
* Token exchange adds one round trip at login.

## Alternatives considered
* **Use IdP tokens directly as API bearer tokens**: less code, but revocation, WebSocket auth and multi-IdP support depend on the vendor.
* **Self-built auth**: rejected (risk, audit requirement).
