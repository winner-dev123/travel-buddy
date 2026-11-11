# ADR-0031: Payments — store billing in the apps, Stripe on the web, one ledger

- **Status:** Accepted
- **Date:** 2026-11-11
- **Deciders:** Product owner (is setting up a Stripe account and asked for a payments architecture that respects App Store and Google Play rules, with plans of configurable price and validity), backend
- **Requirements:** BILL-001..012, NFR-002
- **Confirms:** [ADR-0012](0012-web-billing-provider.md) (Stripe on the web) and [ADR-0017](0017-billing-direct-store-integration.md) (direct App Store and Google Play integration), both now Accepted
- **Related:** [ADR-0006](0006-central-entitlement-evaluation.md) (one entitlement evaluator), [docs/07](../07-subscription-entitlement-policy.md)

## Context

The owner asked for paid plans with configurable prices and validity periods, processed by Stripe. Ten requirements:

1. Configurable plans.
2. Stripe while respecting store policies.
3. Plans and purchase status visible to travellers.
4. Automatic activation.
5. No secret keys in the app.
6. Webhooks for approvals, declines, refunds and cancellations.
7. Transactions recorded per user.
8. Automatic activation and expiry dates.
9. No duplicate payments, and safe webhook processing.
10. Separate test and production environments.

The owner also asked us to check first whether the plans unlock digital features or services used outside the app, and not to build external payments for digital goods without confirming they are allowed.

**Every paid plan is digital and used inside the app:** creating groups and challenges, premium guides and audio tours, AI replanning, more AI itineraries and more offline downloads.

* **Apple, App Store Review Guideline 3.1.1:** unlocking features or content inside the app requires In-App Purchase.
  * *3.1.3(b) multiplatform services:* the app may unlock what the user bought elsewhere (our website), as long as it is also sold as an In-App Purchase.
  * *3.1.3(e):* goods and services used outside the app may use other payment methods.
  * Reader apps (3.1.3(a)) and person-to-person services (3.1.3(d)) don't apply.
* **Google Play Payments policy:** digital goods sold in the app use Google Play Billing. Physical goods and real-world services are exempt.
* **External payment links inside the apps:** allowed only under regional rules that changed repeatedly in 2025–2026 and are partly in litigation.
  * Apple: the US storefront after the 2025 court order; the EU under the DMA with Apple's terms and fees; Japan.
  * Google: alternative billing and external offers programmes, including in the US and the EEA.
  * Brazil: CADE has a case against Apple.

  Our information may be out of date; the current rules for the launch countries need a legal check.

## Decision

**Where each payment happens**

* **Apps (iOS and Android):** App Store and Google Play billing only, verified on the server (ADR-0017). The apps show no web price and no link to buy on the web.
* **Website:** Stripe hosted Checkout and the Customer Portal (ADR-0012). The app recognises plans bought on the web (3.1.3(b)) as long as the same plans are sold in-app.
* **No external payment links** in the apps until legal confirms a region's rules. If allowed later, they would sit behind a per-region server flag.
* If physical goods or real-world services (tours, bookings) are added, Stripe may be used inside the apps for those.
* Every provider feeds the same grants, so `billing.service.has()` stays the only gate (ADR-0006).

**Offers (BILL-010)**

* Three product kinds:
  * subscriptions (`auto_renewable`);
  * **passes** (`non_renewing`): paid once, Premium for a fixed period, never renew;
  * content purchases (`non_consumable`).
* Periods are free-form ISO 8601 (`P7D`, `P2W`, `P3M`, `P1Y`).
* Each offer has titles and descriptions in five languages and a display order, managed through the admin API (superadmin, justified, audited).
* Prices are never stored by us. Stripe prices are read live (cached for 10 minutes) for the web; the apps must show the store's own localised price.
* A pass starts when the traveller's current finite Premium ends, so passes stack. "Premium until" follows back-to-back grants.
* Ends use calendar arithmetic: one month from 31 January is the end of February.

**Ledger and history (BILL-011)**

* `billing_transactions` holds one row per payment, refund or dispute:
  * provider object reference, user, product, subscription or purchase;
  * amount in minor units and currency;
  * reason (`purchase`, `renewal`, `change`, `refund`, `partial_refund`, or a dispute reason);
  * receipt URL, environment and time.
* A row only moves forward (pending → failed → succeeded; open → won or lost), so an event that arrives late can't undo a success.
* Store purchases are recorded too, with amount null when the store doesn't report it.
* `GET /v1/billing/transactions` returns the caller's own rows. The app shows them in Purchase history (SCR-118).
* Travellers are notified when:
  * a payment fails;
  * an asynchronous payment (Pix, boleto) is confirmed;
  * a refund ends a purchase;
  * Premium that won't renew ends within 2–3 days (daily job).

**Webhooks (BILL-005, BILL-006)**

* Every event is verified before anything is read: HMAC over the raw body, 5-minute tolerance.
* From the payload we read only the event's id, type, mode and object id. The object itself is fetched from the Stripe API with a pinned version (`STRIPE_API_VERSION`, default `2025-02-24.acacia`), before the database transaction opens. So the endpoint's own API version doesn't matter, and stale or reordered payloads can't mislead us.
* If Stripe is unreachable we answer 503 and store nothing, so Stripe delivers the event again.
* Each event is stored once by id, with a minimal payload (no personal data).
* Events handled:
  * `checkout.session.completed`, `.async_payment_succeeded`, `.async_payment_failed`, `.expired`;
  * `customer.subscription.created`, `.updated`, `.deleted`, `.paused`, `.resumed`;
  * `invoice.paid`, `invoice.payment_failed`;
  * `charge.refunded`, `charge.dispute.created`, `charge.dispute.closed`.
* A refund revokes exactly what its charge paid for: the invoice's subscription, or the one-time purchase. A full refund always revokes it; a partial refund keeps it unless `STRIPE_PARTIAL_REFUND_REVOKES` is on.
* Disputes are recorded while open. A lost dispute revokes like a full refund.

**No double charges (BILL-006)**

* Checkout is refused with `409` when the user already has the content, or a subscription that is still renewing.
* An open Checkout session for the same offer is handed out again (sessions last 1 hour). A user's checkouts are serialised with an advisory lock.
* If a second web subscription to the same plan still appears (for example, two tabs paid at once), it is cancelled and its first payment refunded (`STRIPE_REFUND_DUPLICATES`, on by default).
* A daily reconciliation job re-reads the web subscriptions that still grant something, cancels duplicates that slipped through, and closes expired Checkout sessions.

**Environments (BILL-012)**

* Production takes a live key (`sk_live_` or, preferably, a restricted `rk_live_` key). Every other environment takes a test key. The API refuses to start otherwise.
* The webhook ignores events from the other mode and records them with the error `wrong_mode`.
* Staging (the Railway environment now called "production", with `APP_ENV=staging`) uses Stripe test mode. A real production environment gets its own Railway environment, database, keys, webhook endpoint and Prices.
* Secrets live only in the platform's variables, never in the apps or the repository (NFR-002).

## Consequences

* Store purchases need the Apple Developer Program and a Google Play developer account, and the products created in both consoles. The backend is ready (BL-6.01); the app's paywall waits for a development build with StoreKit and Play Billing (BL-3.11).
* Store commissions (15–30%) apply to in-app sales, so in-app and web prices may differ. The apps never mention the web price.
* Each webhook makes one to three Stripe API calls. That is acceptable at our volumes, and Stripe's own retries act as the queue.
* Stripe Tax and invoicing obligations (for example, Brazilian fiscal invoices, which Stripe doesn't issue) need a decision with an accountant.

## Alternatives considered

* **Stripe checkout inside the apps for Premium:** violates App Store 3.1.1 and Google Play's payments policy for digital goods. Rejected.
* **Reading webhook payloads directly:** the shape depends on the endpoint's API version, and order isn't guaranteed. Rejected in favour of fetching objects.
* **Storing raw webhook events:** they contain customer emails and addresses. Rejected; the inbox keeps the type and object id only.
* **RevenueCat:** still possible behind the same provider port (ADR-0017). Not needed while direct integration works.
