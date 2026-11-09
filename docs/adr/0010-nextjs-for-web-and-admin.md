# ADR-0010 — One Next.js application for the public site, traveler web app and admin

* **Status:** Accepted. **Supersedes** "Admin web: React + Vite" in [doc 02 §18](../02-system-architecture.md#18-technology-summary).
* **Date:** 2026-11-09

## Context

Doc 02 planned a small Vite admin console. The web brief adds an SEO-critical public site and a full traveler web app, and it asks for all three experiences to share design tokens, the API client and i18n.

## Options

1. **Three apps** (Next.js public, Vite traveler SPA, Vite admin). Maximum isolation, but triple the tooling and duplicated auth and layouts.
2. **One Next.js app with route areas** (`(marketing)`, `(auth)`, `(traveler)`, `admin`). One auth/BFF implementation, one build, and per-route code splitting.
3. **Two Next.js apps** (web + admin). Better isolation for admin, but two deployments.

## Decision

Option 2 now, structured so that option 3 is a mechanical extraction later:

* Admin code lives only under `app/[locale]/admin/**` and `src/features/admin/**`. Nothing outside admin imports it (enforced by ESLint `no-restricted-imports`).
* Route-level code splitting keeps admin JavaScript out of traveler and public bundles.
* The admin layout performs a server-side platform-role check (`support | moderator | admin | superadmin`) and returns `404` to everyone else. The backend authorizes every admin API call again (`require_platform_permission`), so the web check is defence in depth only.
* Admin responses are `Cache-Control: private, no-store` and `X-Robots-Tag: noindex, nofollow`.
* An optional `ADMIN_ALLOWED_HOSTS` setting lets operations serve admin only on a dedicated host from the same build (for example `admin.example.com` behind SSO or an IP allow-list).

## Consequences

* One deployment pipeline. Until admin is extracted, admin incidents (for example a CSP regression) share the blast radius of the main app. This is accepted for the MVP.
* Extraction triggers: separate staff SSO requirements, a separate compliance boundary, or an admin release cadence that diverges from the consumer app.
