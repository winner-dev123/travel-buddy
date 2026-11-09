# ADR-0015: Expo (dev builds) for the React Native app

- **Status:** Accepted
- **Date:** 2026-11-09
- **Related:** [ADR-0009](0009-web-monorepo-layout.md) (monorepo layout; the mobile app currently lives at `mobile/`, and the move to `apps/mobile` is backlog item BL-0.20)

## Context
The master prompt mandates React Native + TypeScript. We need push, secure storage, SQLite, location, background audio, maps and store builds with a small team.

## Decision
Use **Expo** with development builds (prebuild / Continuous Native Generation), **Expo Router** for typed file-based navigation, and EAS Build/Submit/Update for delivery. Native modules not covered by Expo (e.g., MapLibre) are added through config plugins, so the project is not limited to Expo Go.

## Consequences
Faster setup and upgrades, OTA fixes for JS-only changes. Native code is generated (not committed), and customizations must go through config plugins. Under that constraint, `ios/` and `android/` are git-ignored.

## Alternatives considered
Bare React Native CLI: more control, more maintenance.
