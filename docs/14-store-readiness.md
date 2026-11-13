# 14. App Store and Google Play readiness

Status of the store requirements for the mobile app (BL-6.06), with the facts the store forms need.
Update it whenever the app gains a permission, an SDK or a data flow.

**Status (2026-11-11):** the policy features exist in the backend, the app and the staff console. Before
the first submission, close the gaps listed in [§6](#6-gaps-before-the-first-submission).

## 1. User-generated content (App Store Review Guideline 1.2, Google Play UGC policy)

| Requirement | Where it lives | Status |
|---|---|---|
| Filter objectionable content | Moderation states on posts, comments and messages; automated checks on upload (media scanning hook); hidden content never reaches feeds (SAFE-004); staff-managed keyword filter on direct messages from connections younger than 7 days (SAFE-006) | ✅ backend |
| Report content and people | `POST /v1/reports` for users, posts, comments, messages, groups and challenges (SAFE-002); the app reports profiles, stories, comments and messages from their menus (SCR-131) | ✅ |
| Block abusive users | `PUT /v1/users/{id}/block` hides profiles, posts, messages, trips and challenges both ways (SAFE-001); the app blocks from the profile after a confirmation and lists blocked people | ✅ |
| Users control their own content | Authors edit and delete their stories and comments in the app; story authors can remove comments on their stories; feed "hide / not interested"; group admins remove and restrict members | ✅ |
| Act on reports within 24 hours | Moderation queue ordered by priority (SAFE-003), audit, and the staff console (ADR-0032, https://travel-buddy-staff.web.app): queue, evidence, actions on content and authors, the oldest waiting report on the overview | ✅ tooling · ⚠️ staffing rota and the first staff accounts needed |
| Published contact information | Profile → Help & legal (SCR-116): support email (`support` in `/v1/client-config`, `SUPPORT_EMAIL`), help centre link once `SUPPORT_URL` is set, terms, privacy policy and guidelines | ✅ app · ⚠️ store listing and public help page |
| Terms with zero tolerance for abuse | Community guidelines URL from `/v1/client-config` (`legal.community_guidelines_url`), accepted at sign-up | ✅ (legal copy pending) |

## 2. Accounts

| Requirement | Where it lives | Status |
|---|---|---|
| Account deletion inside the app (App Store 5.1.1(v)) | Settings → Delete account (SCR-113): 30-day grace, cancellable, then full deletion (AUTH-010) | ✅ |
| Deletion outside the app (Google Play data deletion URL) | Web route for deletion requests (web session) pointing to the same API | ⚠️ confirm the public URL with the web session |
| Data access (GDPR Art. 15/20) | Settings → Your data: archive within minutes, 7-day link (AUTH-011, BL-6.03) | ✅ |
| Sign in with Apple (App Store 4.8) | Required when the app offers other third-party sign-in. The apps show "Continue with Apple / Google" only for providers listed in `AUTH_SOCIAL_PROVIDERS`, with Apple first on iOS; enable Apple together with Google (docs/11 §1.12) | ✅ built · ⬜ providers to configure in Supabase |
| Minimum age | 18 by default (`MINIMUM_AGE`), birth date at sign-up, under-age sign-ups refused | ✅ |

## 3. Payments

| Requirement | Where it lives | Status |
|---|---|---|
| Digital goods through store billing (App Store 3.1.1, Play Payments policy) | Premium and paid guides through StoreKit / Play Billing; verification server-side (ADR-0017) | ✅ App Store (needs `APPLE_BUNDLE_ID`, `APPLE_ROOT_CA_SHA256`) · ✅ Google Play (needs the Play service account key and the RTDN Pub/Sub push settings, `GOOGLE_*`) |
| No steering to web purchases inside the app | Stripe Checkout exists for the web only; the app shows no web price or link | ✅ keep it that way |
| Plans bought on the website work in the app (App Store 3.1.3(b)) | Allowed only while the same plans are also sold as in-app purchases | ✅ entitlements are provider-neutral (ADR-0006) |
| External payment links (US App Store, EU DMA, Japan; Google alternative billing) | Not built: regional rules changed in 2025–2026 and need legal confirmation per launch country (ADR-0031) | ⏸ decision pending |
| Passes (Premium for a fixed period) | App Store: non-renewing subscription; Google Play: one-time product; Stripe: one-time payment. The backend grants the period (BILL-010) | ✅ backend · ⚠️ products to create in both consoles |
| Subscription disclosure on the paywall (App Store 3.1.2) | SCR-133 states auto-renewal, cancellation 24 hours before the period ends, where to manage it, and links the terms and privacy policy; restore is on the paywall and in Subscription | ✅ text · ⚠️ prices come from StoreKit / Play Billing once the adapter ships |
| Purchase history in the app | Settings → Subscription → Purchase history (SCR-118): information only, receipts open the store's or Stripe's page | ✅ |
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
| Location: coarse | Yes, only while the app is open, to find the city; not stored (PROF-005, NFR-007) | No storage · used transiently | App functionality |
| Location: precise | Yes, only while the app is open and only if the traveller allows precise location: rounded to about 110 m on the device, used for one lookup (city, places near me) and never stored (LOC-003) | No storage · used transiently | App functionality |
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
| Data shared with third parties | No sale or sharing for advertising. Processors: Google (Firebase Auth, Cloud SQL, Cloud Storage, FCM) and Railway (hosting) after the ADR-0028 cutover, Supabase (database, auth) and Vercel (hosting) until then, Anthropic (AI itineraries and translations, only the request text, no account data), Apple and Google for purchases and push |
| Data types | As in §4: email, photos and videos, other user content, messages, approximate and precise location (transient, rounded to about 110 m; ADR-0035), user and device IDs, purchase history |
| Optional collection | Discovery location and post translation are opt-in (consents) |

## 6. Gaps before the first submission

**Google Play specifics (checked 2026-11-11):**

* **Developer account:** register an **organization** account for the company (needs a D-U-N-S number, which can take up to 30 days). A personal account created after 13 Nov 2023 must first run a closed test with at least 12 opted-in testers for 14 days before production access.
* **Target API level:** new apps and updates must target Android 16 (API 36) since 31 Aug 2026. The app targets 36 (React Native 0.88 defaults) ✅.
* **Child Safety Standards policy (social apps):** publish a public web page with standards that explicitly prohibit child sexual abuse and exploitation (CSAE). It must also explain how to report it in the app and how we act, including reporting CSAM to the authorities. Name a child-safety point of contact in Play Console. In-app reporting exists, and the staff console puts `minor_safety` reports first with a warning ✅.
* **Release build:** an Android App Bundle (AAB) signed with an upload key and Play App Signing. The current APK workflow builds debug-signed test APKs only.
* **Play Console declarations:**
  * Data safety (§5);
  * content rating questionnaire, declaring user-generated content and messaging between users;
  * target audience 18+;
  * ads (none);
  * app access (a reviewer demo account);
  * the account deletion web link (§2).

1. **Push notifications:** the app is ready (`expo-notifications`: permission asked in context
   on the Notifications screen, never at launch; token registered per session to
   `POST /v1/users/me/devices`; taps open the right screen). Still needed: the EAS project ID in
   `expo.extra.eas.projectId` and the APNs key / FCM credentials in EAS.
2. ~~Photo uploads~~: done. The composer attaches up to ten photos (system picker or camera),
   uploads them through the presigned flow and finalizes them; permission strings are in
   [§7](#7-device-permissions), localized in five languages.
3. ~~Encryption export compliance~~: done, `ITSAppUsesNonExemptEncryption = false` in
   `ios.infoPlist` (standard HTTPS only).
4. **Support contact:** in the app (Help & legal). Still needed: a public help page on the web
   (web session), then set `SUPPORT_URL` so the app links to it; the same URL goes into both
   store listings.
5. **Review account:** a demo account with sample trips, a group and a challenge, given to App
   Review and Play review in the submission notes.
6. **Store listings:** screenshots in five locales, age rating questionnaires (user-generated
   content, unrestricted messaging between users), privacy policy URL.
7. **Google Play billing:** the code is ready (verification, acknowledgement, RTDN). Still needed:
   a service account with Play Developer API access, a Pub/Sub topic linked in Play Console with
   an authenticated push subscription to `/v1/billing/webhooks/google`, and the four `GOOGLE_*`
   settings (BL-6.01).

## 7. Device permissions

Each permission is asked only when the user starts the action that needs it, never at launch.
iOS usage strings come from the config plugins (English) and `mobile/native-locales/*.json`
(en, es, pt-BR, fr, de, through `expo.locales`).

| Permission | When it is asked | iOS key | Android |
|---|---|---|---|
| Location (while in use) | Opening the Nearby feed tab, "Places near me" or "Use my current location" in search | `NSLocationWhenInUseUsageDescription` (precise is the traveller's choice in the iOS prompt) | `ACCESS_COARSE_LOCATION` and `ACCESS_FINE_LOCATION`: Android 12+ lets the traveller pick approximate or precise; background location blocked. With approximate only, Explore explains that places may be off and links to the settings |
| Photos | Not asked: the system photo picker returns only the photos the user picks | `NSPhotoLibraryUsageDescription` (required by the picker module) | Photo picker, no media permission; legacy storage permissions only up to Android 12 (`maxSdkVersion 32`) |
| Camera | Tapping "Take a photo" in the composer | `NSCameraUsageDescription` | `CAMERA` |
| Microphone | Never (no video recording) | not declared | `RECORD_AUDIO` blocked |
| Notifications | "Turn on" on the Notifications screen | — (system prompt) | `POST_NOTIFICATIONS` (Android 13+) |
