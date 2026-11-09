# Travel Buddy — mobile app

React Native + TypeScript (strict) on **Expo SDK 58** (React Native 0.88, React 19.3),
with Expo Router for navigation. Targets iOS and Android.

> **Phase 0 status:** this is the foundation only. Every tab and flow renders an
> explicit "Coming in Phase N" placeholder driven by `src/config/featureFlags.ts`.
> There is no sample or fake data anywhere in the app.

## Setup

Requirements: Node 20+ (CI uses the repo's pinned version), npm, and the Expo
tooling (`npx expo`). Building a device or simulator app additionally needs
Xcode (macOS) or Android Studio.

```sh
cd mobile
npm install
cp .env.example .env.local   # then edit EXPO_PUBLIC_API_BASE_URL
npm start                    # Expo dev server
```

Native modules used here (secure store, localization, netinfo) work in Expo Go
for development. Production builds use EAS / `expo prebuild` (native folders
are git-ignored and generated).

## Scripts

| Script | What it does |
|---|---|
| `npm start` | Expo dev server (`android` / `ios` / `web` variants) |
| `npm run typecheck` | `tsc --noEmit` (strict, `noUncheckedIndexedAccess`) |
| `npm run lint` | ESLint (`eslint-config-expo` + Prettier), zero warnings allowed |
| `npm run lint:fix` / `npm run format` | Auto-fix lint and formatting |
| `npm test` | Jest (`jest-expo` preset) + React Native Testing Library |
| `npm run test:ci` | Jest in CI mode with coverage |

## Environment variables

`EXPO_PUBLIC_*` values are **inlined into the JS bundle**, so never put secrets in them.

| Variable | Required | Purpose |
|---|---|---|
| `EXPO_PUBLIC_API_BASE_URL` | yes (at first API call) | REST API origin, no trailing slash and no `/v1` |
| `EXPO_PUBLIC_FEATURE_FLAGS` | no | Development builds only: comma-separated feature keys to force-enable. Ignored when `__DEV__` is false |

## Structure

```
app/                         Expo Router routes (file-based)
  _layout.tsx                Root: providers, i18n locale sync, Query online manager
  (tabs)/                    Primary navigation: Home, Explore, Companions, Messages, Profile
  (auth)/sign-in.tsx         Sign-in / register (placeholder, Phase 1)
  (onboarding)/onboarding.tsx  Onboarding entry (placeholder, Phase 1)
  +not-found.tsx
src/
  api/                       Typed HTTP client, problem+json errors, cursor pagination types
    generated/               Future home of types generated from contracts/openapi (see README)
  auth/tokenStore.ts         Access token in memory; refresh token in expo-secure-store
  components/                PhasePlaceholder, FeatureGate, OnlineOnlyBadge, DiscoverySafetyNotice
  config/                    Build-time env, feature flags (phase per feature)
  features/onboarding/       Onboarding step definitions
  i18n/                      i18next setup, locale resolution, en / es / pt-BR / fr / de
  offline/connectivity.ts    NetInfo-based online state + TanStack Query online manager
  query/queryClient.ts       TanStack Query defaults (retry policy for transient errors only)
  state/settingsStore.ts     Zustand: locale override, theme preference
  theme/                     Design tokens (light/dark), WCAG contrast utilities
__tests__/                   Navigation tests (real route files via expo-router/testing-library)
types/                       Ambient declarations for untyped third-party files
```

Path alias: `@/…` → `src/…` (configured in `tsconfig.json` and the Jest `moduleNameMapper`).

## Implemented vs placeholder

| Area | State |
|---|---|
| Navigation shell (5 tabs, auth/onboarding groups, 404) | **Implemented** |
| Feature flags and "Coming in Phase N" placeholders | **Implemented** |
| i18n (5 locales, CLDR plurals, device locale and user override) | **Implemented**. Override is not persisted yet |
| Design tokens, light/dark, contrast tests | **Implemented** |
| API client: `X-Request-ID`, `Accept-Language`, `Authorization`, `Idempotency-Key`, `If-Match`, timeouts, problem+json parsing | **Implemented** (no endpoints are called yet) |
| Token storage (secure store and memory) | **Implemented** |
| Connectivity detection and "Online only" badge | **Implemented** |
| Sign-in, onboarding, feed, discovery, messaging, groups, trips, guides, billing | **Placeholder**. Scheduled per `docs/09-development-backlog.md` |
| Access-token refresh on `401 token_expired` | Not implemented (Phase 1) |
| Settings persistence (expo-sqlite kv-store) and server sync | Not implemented (Phase 1) |
| Generated API types from OpenAPI | Not implemented. See `src/api/generated/README.md` |
| Expo Router typed routes (`experiments.typedRoutes`) | Off, so CI type-checks without running the dev server |
| E2E (Maestro) | Not set up yet (Phase 1) |

## Conventions

- **Never show fake data.** Unreleased features render `FeatureGate` → `PhasePlaceholder`.
- **Online-only features are labelled** with `OnlineOnlyBadge`. Offline-capable
  features (saved trips, downloaded guides) must work without it.
- **Discovery copy never calls meeting strangers "safe".** Reuse `DiscoverySafetyNotice`.
- **Accessibility:** 44×44 minimum touch targets (`theme.minTouchTarget`), headers
  marked with `accessibilityRole="header"`, every icon-only control labelled, and
  text that scales with dynamic type (no fixed-height text containers).
- **i18n:** every user-facing string goes through `t()`. Keys are type-checked
  against `en.json`, and the parity test enforces the same key set and plural forms
  in every locale. Use logical `start`/`end` styles (not `left`/`right`) for RTL readiness.
- **Mutations:** generate the `Idempotency-Key` once per user action and reuse it on retry.
