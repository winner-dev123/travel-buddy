# 14. App Store and Google Play readiness

Status of the store requirements for the mobile app (BL-6.06), with the facts the store forms need.
Update it whenever the app gains a permission, an SDK or a data flow.

**Status (2026-11-10):** the policy features exist in the backend and mostly in the app. Before
the first submission, close the gaps listed in [§6](#6-gaps-before-the-first-submission).

## 1. User-generated content (App Store Review Guideline 1.2, Google Play UGC policy)

| Requirement | Where it lives | Status |
|---|---|---|
| Filter objectionable content | Moderation states on posts, comments and messages; automated checks on upload (media scanning hook); hidden content never reaches feeds (SAFE-004) | ✅ backend |
| Report content and people | `POST /v1/reports` for users, posts, comments, messages, groups and challenges (SAFE-002); mobile report sheet (SCR-131) | ✅ |
| Block abusive users | `PUT /v1/users/{id}/block` hides profiles, posts, messages, trips and challenges both ways (SAFE-001); mobile blocked list | ✅ |
| Act on reports within 24 hours | Moderation queue ordered by priority (SAFE-003), staff tools and audit; `GET /v1/admin/ops/summary` shows the oldest open report | ✅ tooling · ⚠️ staffing rota needed |
| Published contact information | Support address in the app (Settings) and the store listing | ⚠️ add to Settings before submission |
| Terms with zero tolerance for abuse | Community guidelines URL from `/v1/client-config` (`legal.community_guidelines_url`), accepted at sign-up | ✅ (legal copy pending) |

## 2. Accounts

| Requirement | Where it lives | Status |
|---|---|---|
| Account deletion inside the app (App Store 5.1.1(v)) | Settings → Delete account (SCR-118): 30-day grace, cancellable, then full deletion (AUTH-010) | ✅ |
| Deletion outside the app (Google Play data deletion URL) | Web route for deletion requests (web session) pointing to the same API | ⚠️ confirm the public URL with the web session |
| Data access (GDPR Art. 15/20) | Settings → Your data: archive within minutes, 7-day link (AUTH-011, BL-6.03) | ✅ |
| Sign in with Apple (App Store 4.8) | Required only when the app offers other third-party sign-in; the app uses email and password | ✅ not required today · add with any social login |
| Minimum age | 18 by default (`MINIMUM_AGE`), birth date at sign-up, under-age sign-ups refused | ✅ |

## 3. Payments

| Requirement | Where it lives | Status |
|---|---|---|
| Digital goods through store billing (App Store 3.1.1, Play Payments policy) | Premium and paid guides through StoreKit / Play Billing; verification server-side (ADR-0017) | ✅ App Store (needs `APPLE_BUNDLE_ID`, `APPLE_ROOT_CA_SHA256`) · ⚠️ Google Play verification needs a Play service account |
| No steering to web purchases inside the app | Stripe Checkout exists for the web only; the app shows no web price or link | ✅ keep it that way |
| Restore purchases | `POST /v1/billing/purchases/restore`; paywall has a restore action | ✅ |
| Challenge prizes | No cash, cash equivalents, raffles, wagers or paid entry (CHAL-013); sponsored rewards reviewed by staff (CHAL-014) | ✅ |

## 4. App Store privacy label ("nutrition label")

Tracking: **none** (no advertising SDKs, no data shared with data brokers, no cross-app
tracking). Third-party SDKs: Expo modules only; no analytics or crash-reporting SDK in the app
today. If one is added, update this table and the label.

| Data type (Apple) | Collected | Linked to the user | Purpose |
|---|---|---|---|
| Contact info: email address | Yes | Yes | App functionality (sign-in, account notices) |
| User content: photos or videos | Yes (uploads) | Yes | App functionality |
| User content: other (posts, comments, trips, challenge answers) | Yes | Yes | App functionality |
| User content: messages (direct and group chats) | Yes | Yes | App functionality |
| Location: coarse | Yes, only while the app is open and only to pick the city; not stored (PROF-005, NFR-007) | No storage · used transiently | App functionality |
| Location: precise | No (fine location is blocked on Android and not requested on iOS) | – | – |
| Identifiers: user ID | Yes | Yes | App functionality |
| Identifiers: device ID | Yes (push registration, per session) | Yes | App functionality |
| Purchases: purchase history | Yes | Yes | App functionality |
| Diagnostics | No in-app crash SDK; server logs carry request IDs, no content | – | – |
| Sensitive info, health, financial info, browsing history, contacts | No | – | – |

## 5. Google Play data safety form

| Question | Answer |
|---|---|
| Data encrypted in transit | Yes (TLS 1.2+, NFR-006) |
| Users can request deletion | Yes (in the app and on the web) |
| Data shared with third parties | No sale or sharing for advertising. Processors: Supabase (database, auth), Vercel (hosting), object storage, Anthropic (AI itineraries and translations, only the request text, no account data), Apple and Google for purchases and push |
| Data types | As in §4: email, photos and videos, other user content, messages, approximate location (transient), user and device IDs, purchase history |
| Optional collection | Discovery location and post translation are opt-in (consents) |

## 6. Gaps before the first submission

1. **Push notifications:** add `expo-notifications` (permission prompt with purpose text, token
   registration to `POST /v1/users/me/devices`) and the APNs key / FCM credentials.
2. **Photo uploads:** when the picker lands, add `NSPhotoLibraryUsageDescription` /
   `NSCameraUsageDescription` strings in all five locales.
3. ~~Encryption export compliance~~: done, `ITSAppUsesNonExemptEncryption = false` in
   `ios.infoPlist` (standard HTTPS only).
4. **Support contact** in Settings and a public support page.
5. **Review account:** a demo account with sample trips, a group and a challenge, given to App
   Review and Play review in the submission notes.
6. **Store listings:** screenshots in five locales, age rating questionnaires (user-generated
   content, unrestricted messaging between users), privacy policy URL.
7. **Google Play billing:** Play Developer API service account for purchase verification and Real-time
   Developer Notifications (BL-6.01).
