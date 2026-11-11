# ADR-0032: A standalone staff console on its own origin

- **Status:** Accepted
- **Date:** 2026-11-11
- **Deciders:** Product owner (asked for a web dashboard to manage the app and chose a separate admin site), backend
- **Requirements:** ADM-001..009, SAFE-003, BILL-009, BILL-011
- **Amends:** [ADR-0010](0010-nextjs-for-web-and-admin.md) for the admin area only: the public site and the traveller web app stay one Next.js app. This is ADR-0010's own "option 3", taken early.
- **Related:** [ADR-0020](0020-supabase-auth-identity-provider.md) and [ADR-0028](0028-firebase-platform-and-railway-hosting.md) (identity), docs/11 §1.15 (setup), docs/14 (store readiness)

## Context

The apps let people post, message and form groups. Both stores require that kind of app to act on reports quickly (App Store Guideline 1.2, Google Play User Generated Content policy and the Child Safety Standards policy). The backend already has the staff API (`/v1/admin/*`), with platform roles, a mandatory second factor, 30-minute idle and 12-hour absolute staff sessions, and an audit justification on every sensitive call. But nobody could use it: the planned admin pages in the website (web backlog Phase 8) had not been started, and the web session has been offline since 2026-11-09.

The owner asked for a web dashboard to manage the app. Offered "a separate admin site" or "inside the public website", they chose the separate site.

## Decision

1. **A separate app in `admin/`:** React 19, Vite and TanStack Query, a static single-page app with no server code. It is a standalone npm project like `mobile/`, owned by the backend/mobile workstream, with its own CI (`ci-admin.yml`).
2. **Its own origin:** Firebase Hosting site `travel-buddy-staff` (`https://travel-buddy-staff.web.app`) in the existing Firebase project. Nothing links to it and it is never indexed. Strict headers:
   - a CSP whose `connect-src` allows only the API and Firebase Authentication, with no inline scripts;
   - `frame-ancestors 'none'`, HSTS, no referrer.
   Deploys go through the Hosting REST API (`admin/scripts/deploy-hosting.mjs`), with no firebase-tools and no secrets in the repository.
3. **Sign-in:** Firebase email and password over REST (as the apps do), then a **TOTP authenticator code**.
   - A staff account without a second factor is offered TOTP enrollment only after the API confirms it holds a platform role.
   - The resulting ID token carries `firebase.sign_in_second_factor`, which the backend maps to `amr: mfa` (ADM-007).
   - TOTP needs Firebase Authentication with Identity Platform (docs/11 §1.15).
4. **Tokens:** the platform access token stays in memory. The refresh token is kept in `sessionStorage`, for this tab only and never across tabs. Cookies are never used (`credentials: 'omit'`), so there is no CSRF surface. The CSP and the absence of third-party scripts limit what XSS could reach. The API's staff session limits still apply.
5. **Audit justification (ADM-009):** after signing in, staff state what they are working on (10 to 500 characters). It is sent as `X-Audit-Justification` on every `/v1/admin/*` call and stored with each audit entry, and it can be changed at any time. Actions also keep their own notes (suspension notes, resolution notes, grant reasons).
6. **What the API added for the console:**
   - `GET /v1/admin/users`: search by exact email, ID, handle or name. Rows carry no email, and every search is audited.
   - `GET /v1/admin/metrics/overview`: real aggregates only. Money and the privacy queue appear only for roles allowed to see them.
   - `GET /v1/admin/billing/transactions`: the ledger, audited.
   - `PUT` and `DELETE /v1/admin/users/{id}/roles/{role}`: superadmins only. Removing a role ends the account's sessions. The last superadmin cannot be removed.
   - The report's `target_author`, so moderators can act on the person behind the content.
   - CORS allows the `X-Audit-Justification` header.
   - `python -m app.modules.admin.grant_role` gives the first superadmin.
7. **Roles drive the UI:** each page appears only for roles with its permission. Every call is authorised again by the API.

## Consequences

- Staff tools exist before the store submissions. Their releases no longer depend on the public website's.
- An incident in the console (a CSP mistake, say) can't affect the public site or the traveller web app, and the reverse holds too.
- There are two web front ends to maintain, with design tokens shared by copy (the console uses the apps' "Noir" values and self-hosts the same OFL fonts).
- **Staff accounts with TOTP can't sign in to the mobile app yet:** the app's Firebase REST sign-in doesn't handle the second-factor step. Use separate staff accounts (for example `name+staff@company`) until the app supports it.
- The web backlog's Phase 8 admin stories (WEB-P8-001..012) are now covered by the console. The web session should not build them again; docs/09 records the mapping.
- `CORS_ALLOWED_ORIGINS` on every API environment must list the console's origin.

## Alternatives considered

- **Admin pages inside the Next.js site (ADR-0010):** that would share the public site's blast radius and wait for the offline web session. The owner preferred a separate site.
- **A second Next.js app with a BFF and session cookies:** this gives HttpOnly cookies, but needs a server runtime and its own hosting. It also requires CSRF protection. A static app with in-memory tokens and a strict CSP fits a handful of staff users.
- **SMS second factor:** SIM-swap risk and per-message cost. TOTP is free and stronger.
- **Firebase Hosting default site (`travel-buddy-tb.web.app`):** kept free for a possible public use. The name `travel-buddy-admin` was taken by another project.
