# ADR-0009 — Web monorepo layout with npm workspaces

* **Status:** Accepted
* **Date:** 2026-11-09
* **Context docs:** [02 — System architecture](../02-system-architecture.md), [Web 01](../web/01-architecture.md)

## Context

The repository holds only planning documents. Doc 02 implies a `backend/` (Python) directory and a `mobile/` Expo app. The web brief asks for a modular monorepo with `apps/web` and shared `packages/*`, and it puts the mobile app in `apps/mobile` when it uses Expo Router (doc 02 §18 says it does).

## Decision

* JavaScript/TypeScript code lives in an **npm workspaces** monorepo: `apps/*` and `packages/*`.
* `apps/web` is the Next.js application. `apps/mobile` is the eventual home of the Expo app. **For now the Expo app stays at `mobile/` as a standalone npm project with its own lockfile and is not a root workspace member.** Two concurrent work streams running `npm install` against one root lockfile would corrupt it. Moving `mobile/` → `apps/mobile` and switching it to the shared `i18n`, `api-client` and `domain-types` packages is a later, coordinated step (backlog BL-0.20).
* Shared IaC and compose files live in `infra/`, owned by the backend/infra stream. The web container image is defined in `apps/web/Dockerfile`, and web CI in `.github/workflows/ci-web.yml`.
* `backend/` stays at the repository root as doc 02 describes. It is a Python project and is **not** an npm workspace.
* Shared packages: `domain-types`, `validation`, `api-client`, `i18n` and `config` are platform-neutral and usable by React Native. `ui` is web-only.
* Internal packages publish TypeScript source (`"exports"` pointing at `src`). Apps compile them (`transpilePackages` in Next.js; Metro in Expo). There is no build step and no versioning for internal packages.
* npm was chosen over pnpm/yarn because it ships with Node and needs no extra install on contributor machines or CI. Turborepo can be added later for task caching without changing the layout.

## Consequences

* Platform-neutral packages must not import DOM, Node or Next.js APIs from their root entry. Server-only code (for example the mock adapter) uses a separate subpath export.
* npm hoists dependencies. React Native's single-React-copy requirement will need `overrides` when the mobile app joins the workspace as `apps/mobile`.
* `.gitignore` covers `apps/mobile/ios` and `apps/mobile/android` in addition to the legacy `mobile/` entries.
