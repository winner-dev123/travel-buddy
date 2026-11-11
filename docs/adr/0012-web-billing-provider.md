# ADR-0012 — Web subscriptions through Stripe behind the billing provider port

* **Status:** Accepted (the owner chose Stripe; confirmed and extended by [ADR-0031](0031-payments-store-first-stripe-web-ledger.md), 2026-11-11).
* **Date:** 2026-11-09
* **Related:** [doc 02 §10](../02-system-architecture.md#10-entitlements), [07 — Subscription and entitlement policy](../07-subscription-entitlement-policy.md), [ADR-0006](0006-central-entitlement-evaluation.md)

## Context

Doc 02 covers App Store and Google Play subscriptions only. The web needs its own purchase path. The brief forbids storing card data and requires backend-verified entitlements.

## Decision

* Add **Stripe** as a third `BillingProvider` adapter in the backend `billing` module. The web never talks to Stripe with a secret key.
* **Checkout.** The web calls `POST /v1/billing/checkout-sessions {product_id, success_path, cancel_path}`. The backend creates a Stripe Checkout Session and returns its URL, and the web redirects to it. Checkout is a hosted page, so card data never touches our servers (PCI scope SAQ-A).
* **Source of truth.** Stripe webhooks go to `POST /v1/billing/webhooks/stripe` on the backend. They are signature-verified, stored once in `billing_events`, and processed into `subscriptions` and `subscription_entitlements` exactly like store notifications. `/membership/success` **does not** grant anything: it polls `GET /v1/billing/entitlements` (canonical endpoint per doc 07 §7) until the entitlement appears, and shows a message if it times out.
* **Management.** `POST /v1/billing/portal-sessions` returns a Stripe Customer Portal URL for web-purchased subscriptions. Store-purchased subscriptions show a link to the App Store / Google Play management page instead.
* **Cross-platform.** One user may hold entitlements from several providers, and `billing.service.has()` evaluates their union. The pricing page hides web purchase when an active store subscription already grants the same entitlement, so users are not double-charged.
* **Store policy.** The mobile apps do not link to web checkout unless the store rules for that region allow it. That is a mobile concern; it is recorded here so the web pricing page does not assume deep links from apps.

## Consequences

* Taxes and invoices are delegated to Stripe Tax / Billing (to be confirmed with finance).
* Until the backend adapter exists, checkout endpoints answer `503 feature_not_available_in_mock`, and the pricing page shows plans without a working buy button. Payments are never simulated.
