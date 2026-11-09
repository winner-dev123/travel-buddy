# ADR-0006: Central server-side entitlement evaluator

- **Status:** Accepted
- **Date:** 2026-11-09
- **Requirements:** BILL-003, BILL-007, GRP-001, GRP-009

## Context
Premium features span groups, challenges, guides, offline and AI. Scattered `if user.is_premium` checks drift and are easy to bypass. Store state is complex (grace, retry, pause, refund), and grants can come from several providers (Apple, Google, Stripe on web per [ADR-0012](0012-web-billing-provider.md), promotions).

## Decision
* `backend/app/modules/billing/entitlements.py` holds a **pure** evaluator: `(grants, now, config) → EntitlementSnapshot` with `has(Feature)` and `quota(Quota)`. It evaluates the **union** of active grants from all providers. Group premium status is a pure function of the owner's grants and the admin grace period (`group_premium_status`).
* Store and Stripe events are normalized into `subscription_entitlements` grants with `starts_at`/`ends_at`/`revoked_at`, so expiry requires no job.
* `billing.service.has()` is the only gate other modules may call. The client never sends entitlement claims.
* Feature and quota values are configuration.

## Consequences
* There is one place to test and audit, and policy changes need no app release.
* The evaluator must be fast. A Redis cache (60 s) is invalidated by grant events.

## Alternatives considered
* **Entitlements inside JWT claims**: stale for up to the token lifetime and couples billing to auth. Rejected (it may be added as a display hint, never trusted for authorization).
