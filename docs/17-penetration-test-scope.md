# 17. Penetration test scope and rules of engagement

Brief for the external penetration test before the v1.0 launch (BL-6.07, NFR-006: OWASP ASVS
level 2 for the API). It tells the testers what to test, where, with which accounts, and how
findings are reported and fixed. The threat model it builds on is [docs/08](08-privacy-security-threat-model.md).

## 1. Targets

| Target | What | Notes |
|---|---|---|
| Platform API | FastAPI backend on the **staging** deployment (URL in the engagement letter) | The contract is `contracts/openapi/openapi.yaml`; every operation names its rate-limit class and, for staff, its permission |
| Web app | Next.js app and its BFF (`/api/*`), staging | Cookie sessions (ADR-0011); CSRF, cache and revalidation webhook in scope |
| Mobile apps | Android APK from the `mobile-apk` workflow, iOS TestFlight build | Local storage of tokens (secure store), deep links, offline packages |
| Staff (admin) API | `/v1/admin/*` on staging | Needs staff accounts with TOTP (§3) |
| Webhooks | Stripe, App Store Server Notifications, Google Play RTDN (Pub/Sub push), web cache revalidation | Authenticity checks are the target: signatures, JWS chains, OIDC tokens |
| Realtime | Message delivery and tickets (ADR-0013, ADR-0023) | Ticket replay and cross-conversation access |

**Out of scope:** production; denial of service and load (covered by BL-6.04); third-party
platforms themselves (Supabase, Vercel, Anthropic, the stores; follow their own disclosure
programmes); social engineering and physical access; other customers' tenants on shared hosts.

## 2. Priorities

Spend the most time where a flaw hurts users most. Each line points to the threat-model section
and to the tests that already cover the control, so testers can try to break the assumption
rather than re-test the happy path.

| Area | What to try | Threats (docs/08) | Existing tests |
|---|---|---|---|
| Location privacy | Recover a traveller's position from discovery (trilateration, timing, rounding, cross-city browsing, blocked users) | §4.1, T-LOC-01..04 | `backend/tests/integration/test_discovery.py` |
| Object-level authorization | Read or change another user's posts, trips, messages, groups, challenges, data exports, rewards by id (BOLA/IDOR); hidden and blocked content | §4.3 | `test_trip_visibility.py`, `test_challenge_security.py`, `test_people.py` |
| Staff access | Use a lower role for a higher action; skip `X-Audit-Justification`; act without MFA; read personal data without an audit entry | §4.3, ADM-007/008 | `test_moderation.py`, `test_admin_ops.py`, `test_admin_data_requests.py` |
| Sessions | Token replay after sign-out or deletion, refresh rotation, device id confusion, IdP token used as a platform token | §4.2 | `test_identity_flows.py` |
| Billing | Forge or replay a store purchase; reuse one purchase on two accounts; spoof a Stripe, Apple or Google notification; race restore and refund | §4.6 | `test_billing.py`, `test_apple_billing.py`, `test_google_billing.py`, `test_google_play.py` |
| Challenges and prizes | Submit after the deadline, answer twice, read other answers, steer the AI judge with the answer text, claim a reward that isn't yours | §4.7, §4.10 | `test_challenges.py`, `test_challenge_results.py` |
| Media | Type confusion, oversized or decompression-bomb images, EXIF/GPS leakage, reaching quarantined objects, presigned URL reuse | §4.8 | `test_media.py` |
| Injection | SQL, JSON, header and log injection; cursor tampering (HMAC cursors); idempotency key replay with another body | §4.9 | `unit/test_pagination.py`, idempotency cases in `test_billing.py`, `test_messaging.py`, `test_challenges.py` |
| AI | Prompt injection through trips, places and answers; data from other users reaching a prompt; cost abuse past quotas | §4.10 | `test_ai_itineraries.py`, `test_ai_replan.py` |
| Data rights | Export links (HMAC tokens, expiry, re-check), another user's archive, secrets in the archive | AUTH-011 | `test_data_exports.py`, `test_admin_data_requests.py` |
| Offline packages | Download without a licence, licence on more devices than the quota, manifest signature bypass | OFF-001 | `test_offline_packages.py` |

## 3. Accounts and data

Staging only, with synthetic data. The team creates before the test:

| Account | Purpose |
|---|---|
| 2 regular users (A, B), verified email | Cross-account access attempts |
| 1 premium user (staff grant) | Premium-only features, quotas |
| 1 group owner with a group, a challenge and a team | Group and challenge permissions |
| support, moderator, admin, superadmin (one each, TOTP enabled) | Staff role boundaries; the admin API requires MFA |
| 1 blocked pair, 1 private account | Block and privacy enforcement |

Store sandbox purchases: App Store sandbox and Play license testers, set up by the team. Testers
must not use real payment methods.

## 4. Rules

* Test window, source IPs and contacts are fixed in the engagement letter. Tell the team before
  any test that could send emails or push notifications at volume.
* Rate limits stay on. Testers may ask for a temporary allow-list of their IPs for authorization
  testing; never for brute-force tests.
* Stop and report at once (do not continue exploiting) on: access to another user's personal
  data, code execution, credential or key exposure, or anything that touches production.
* Do not keep personal data found during the test beyond the report; redact it in evidence.

## 5. Reporting and fixing

| Severity (CVSS 4.0) | Fix target | Retest |
|---|---|---|
| Critical | Mitigation within 24 hours, fix before launch | Required |
| High | Fix before launch | Required |
| Medium | Within 30 days or before launch if it touches location, messages or payments | Sampled |
| Low / informational | Backlog, decided case by case | — |

Each finding becomes a backlog item linked from BL-6.07 with the report id, the affected
operation(s) and a regression test. The launch go/no-go needs zero open critical and high
findings.

## 6. Checks the team runs before the test

* CI: secret scanning (gitleaks), backend dependency audit (`pip-audit --strict`), mobile
  dependency audit (`npm audit --omit=dev --audit-level=high`), type checks, contract tests, the
  import-boundary test and the full integration suite.
* Supabase exposure check: every `public` table has row level security with no policies and the
  Data API roles hold no grants (verified on 2026-11-10 at migration 0041: 88 tables, 0 exposed).
* Security headers, TLS configuration and CORS on staging (web session for the web app).
