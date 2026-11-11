# 15. Records of processing activities (GDPR Art. 30)

Draft for the privacy review (BL-6.05, SAFE-010). It consolidates the lawful basis register
([docs/08 §5.1](08-privacy-security-threat-model.md)), the retention schedule
([docs/04 §14](04-database-erd.md)) and the discovery DPIA ([docs/13](13-dpia-traveler-discovery.md)).
Legal review must confirm the bases, retention periods and transfer mechanisms before launch.

**Controller:** Travel Buddy (legal entity and representative to be filled in before launch).
**Contact for data subjects:** privacy@travelbuddy.app.
**Data subjects:** registered users (18+), people mentioned in user content, staff.

## 1. Processing activities

| # | Activity | Purpose | Data categories | Basis (Art. 6) | Retention | Recipients |
|---|---|---|---|---|---|---|
| 1 | Accounts and sign-in | Run the account, secure sessions | Email, birth date (age gate), IdP subject, sessions (device, platform, last IP), consents | Contract; legitimate interest (security) | Account life; deleted 30 days after a deletion request | Supabase (auth, database), Vercel (hosting) |
| 2 | Profiles and social features | Profiles, posts, comments, reactions, follows, bookmarks | Profile fields, user content, photos and videos | Contract | Until deleted by the user (+30-day undo) | Supabase, object storage |
| 3 | Destination feed and "nearby" | Show content for a chosen or the current city | Selected destinations; approximate device location used transiently, never stored | Contract; consent (OS permission) for device location | Selections: account life; location: not stored | – |
| 4 | Traveler discovery | Let opted-in travellers find each other at a destination | Discovery session (destination, dates, visibility) | **Consent** (separate, withdrawable, instant effect) | Session expiry; see DPIA | – |
| 5 | Connections and messaging | Direct, group, team chats | Messages, attachments, receipts, reactions | Contract | Life of the conversation; erased on account deletion | Supabase, object storage, push providers (Apple, Google, Expo) for notifications |
| 6 | Travel groups | Organise group trips | Memberships, roles, invitations | Contract | Account or group life | – |
| 7 | Trips and saved places | Plan trips, share with collaborators | Trips, itinerary items, saved places, collaborators | Contract | Until deleted | – |
| 8 | AI itineraries and replanning | Generate trip proposals on request | Request (destination, dates, pace, interests); proposal | Contract (user-initiated) | Request until answered; proposal 30 days; metadata 13 months | Anthropic (model provider, no account data sent) |
| 9 | Post translation | Machine-translate posts on request | Post text, target language | Consent (`post_translation`) | Cached 90 days | Anthropic |
| 10 | Group challenges | Riddles, answers, judging, winners, rewards | Answers, attempts, teams, AI judge rationale (judges only), disputes, badges, reward fulfillment (discount codes encrypted) | Contract | Challenge life; reward records as billing-adjacent records (legal review) | Anthropic (AI judging: riddle and answer text only), sponsors (only the reward a winner receives) |
| 11 | Subscriptions and purchases | Sell premium and paid content | Store transaction IDs, purchase history, entitlements | Contract; legal obligation (tax) | 7 years, pseudonymized on account deletion | Apple, Google, Stripe |
| 12 | Notifications | In-app and push notifications | Notification records, device push tokens (encrypted) | Contract; consent for marketing | Notifications per retention schedule; tokens until the session ends | Apple (APNs), Google (FCM), Expo, Web Push services |
| 13 | Safety and moderation | Handle reports, enforce guidelines | Reports, evidence snapshots, moderation actions, restrictions | Legitimate interest (LIA documented); legal obligation where required | Reports 12 months after resolution; actions 3 years | Staff only |
| 14 | Staff audit | Accountability for staff access | Audit log (actor, action, resource, justification) | Legitimate interest; legal obligation | 24 months | Staff (superadmins) |
| 15 | Data-subject requests | Access and deletion | Request records, export archives | Legal obligation | Requests kept for accountability; archives 7 days | – |
| 16 | Abuse prevention | Rate limiting, abuse signals | IP prefixes, request counters, signal records | Legitimate interest | Hours to days (counters); signals per schedule | – |

## 2. Processors

| Processor | Service | Location | Transfer mechanism |
|---|---|---|---|
| Google (Firebase) | Authentication (Firebase Auth), Android push (FCM) (ADR-0028) | Global (Firebase Auth); EU options to be reviewed | Google Cloud / Firebase DPA, SCCs |
| Railway | API and worker hosting (ADR-0028) | US East | DPA, SCCs |
| Supabase | Postgres and object storage (ADR-0029) | `us-east-1`; EU project if the launch markets require it | DPA; SCCs if outside the EEA |
| Vercel | API and web hosting, cron | Global edge, functions region-pinned | DPA, SCCs |
| Object storage (S3-compatible) | Media, offline packages, export archives | To be chosen | DPA, SCCs |
| Anthropic | AI itineraries, translation, challenge judging | US | DPA, SCCs, no training on API data |
| Apple, Google | Store billing, push notifications | US / global | Their platform terms |
| Stripe | Web payments | US / EU | DPA, SCCs |
| Expo | Push relay for the mobile app | US | DPA, SCCs |

## 3. Security measures (Art. 32 summary)

TLS 1.2+ everywhere; secrets in the platform secret store; row-level authorization in the API
(every query scoped to the caller); push tokens, reward codes and export links encrypted or
HMAC-signed; staff access needs MFA, a justification and is audited; backups with point-in-time
recovery (NFR-004, BL-6.09); dependency and secret scanning in CI (NFR-006); threat model in
[docs/08](08-privacy-security-threat-model.md).

## 4. Data-subject rights

| Right | How |
|---|---|
| Access, portability (Art. 15, 20) | Settings → Your data: ZIP archive of every module's records (AUTH-011) |
| Erasure (Art. 17) | Settings → Delete account: 30-day grace, then deletion or anonymization across modules (AUTH-010) |
| Rectification (Art. 16) | Profile and settings screens; other corrections through support, recorded as a request and closed with the outcome |
| Objection, restriction | Discovery and translation consents withdrawable at once; support for the rest |

Requests that reach support by email or post are recorded in the admin API
(`POST /v1/admin/users/{id}/data-requests`, permission `privacy.requests.manage`): an export
starts the same archive job as the in-app request, a rectification is closed with
`/resolve` and the outcome told to the user. Deletion is always confirmed by the user in the
app. The staff queue (`GET /v1/admin/data-requests`) lists open requests oldest first with the
one-month deadline of Art. 12(3) (`due_at`, `overdue`); every read and change is audited with
a justification. The user sees each request and its status under Settings → Your data.

## 5. Open items for the privacy review

1. Controller details, EU representative (if needed) and DPO decision.
2. Supabase region for the database and storage (EU project if the launch markets require it, ADR-0029).
3. Legal confirmation of retention for billing records, reward fulfillment and moderation evidence.
4. Legitimate interest assessments for moderation, audit and abuse prevention (referenced in docs/08).
5. Sign-off of the discovery DPIA (docs/13) and a short DPIA screening for AI judging of answers.
