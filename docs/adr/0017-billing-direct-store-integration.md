# ADR-0017: Direct App Store / Play integration behind a billing port

- **Status:** Accepted (built in BL-3.01 and BL-6.01; confirmed by [ADR-0031](0031-payments-store-first-stripe-web-ledger.md), 2026-11-11)
- **Date:** 2026-11-09
- **Requirements:** BILL-002..006
- **Related:** [ADR-0012](0012-web-billing-provider.md) (Stripe for web purchases, behind the same port)

## Context
In-app digital subscriptions must use Apple and Google billing. Options are direct integration (App Store Server API + Notifications v2, Google Play Developer API + RTDN) or an aggregator (e.g., RevenueCat).

## Decision (proposed)
Integrate directly behind a `BillingProvider` port (`verify_purchase`, `parse_notification`, `fetch_status`). Normalize into the subscription state machine in [policy doc 07](../07-subscription-entitlement-policy.md). Adapters: `apple`, `google`, `stripe` (web, ADR-0012), and `dev` (development and tests only, with a production boot guard).

## Consequences
No third-party revenue share and full data ownership. More integration code and edge cases. If time-to-market dominates, a RevenueCat adapter can implement the same port (its webhooks feed the same normalized state machine) without touching the rest of the system.
