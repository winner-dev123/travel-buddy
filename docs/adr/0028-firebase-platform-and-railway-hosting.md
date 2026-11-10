# ADR-0028: Firebase platform (Auth, Cloud SQL for PostgreSQL, Cloud Storage, FCM) and Railway hosting

- **Status:** Accepted (cutover pending: the code supports both platforms until the Firebase project is configured)
- **Date:** 2026-11-10
- **Deciders:** Product owner ("Everything on Firebase", database "Firebase PostgreSQL"; backend on Railway), backend
- **Requirements:** AUTH-001..007, AUTH-010, ADM-007, NFR-003, NFR-004, NFR-006, SAFE-010
- **Supersedes:** [ADR-0018](0018-supabase-managed-postgres.md) (database), [ADR-0019](0019-backend-api-hosting.md) (API hosting), [ADR-0020](0020-supabase-auth-identity-provider.md) (identity provider)
- **Amends:** [ADR-0022](0022-media-object-storage.md) (storage vendor), [ADR-0003](0003-oidc-idp-with-platform-sessions.md) (vendor choice)

## Context

The product owner already uses Firebase and asked to move the whole platform there, with the backend on Railway. Two Firebase databases were considered:

* **Firestore**, a document database. The backend's data layer (89 tables, transactions with the outbox, location search, text search, 1,000+ tests) would have to be rewritten, and an extra search service would be needed.
* **Cloud SQL for PostgreSQL**, the database behind Firebase Data Connect, inside the same Firebase (Google Cloud) project. The backend keeps its code, migrations and tests.

The owner chose Cloud SQL for PostgreSQL. Railway runs long-lived containers, so the `worker` role (ADR-0004) can run as its own process. Staging currently runs no background jobs, because Vercel has no worker (docs/11 §1.1).

## Decision

1. **Identity: Firebase Authentication.** Email and password first. Google and Apple sign-in through Firebase are a follow-up (BL-6.12).
   * **Trust.** The backend trusts the project's ID tokens once `FIREBASE_PROJECT_ID` is set: RS256, issuer `https://securetoken.google.com/<project>`, audience `<project>`, Google's public JWKS. The generic OIDC verifier reads Firebase's claims:
     * `firebase.sign_in_provider` sets the identity method (password, Google, Apple), and anonymous sign-ins are refused;
     * `firebase.sign_in_second_factor` counts as `mfa` for staff policies (ADM-007).
   * **Account check at sign-in.** With `FIREBASE_WEB_API_KEY`, the backend looks the account up (`accounts:lookup`, with the user's own ID token). Tokens of disabled or deleted accounts, and tokens revoked by a password change, are refused. The account's `validSince` takes the place of Supabase's recovery marker: when it moves (password change or reset), the first sign-in ends every older session (AUTH-005). The time is recorded at registration, so the account's creation time never counts as a change. If the lookup can't be completed, sign-in proceeds and the failure is logged. The Web API key only identifies the project and ships in the apps.
   * **Account deletion.** The deletion saga deletes the Firebase account through the Identity Toolkit Admin API (`accounts:delete`) with a service account (`GOOGLE_SERVICE_ACCOUNT_JSON`, role Firebase Authentication Admin). It uses the OAuth 2.0 JWT-bearer grant, signed with PyJWT, so no extra dependency is needed (AUTH-010).
   * **Apps.** Both apps call the Identity Toolkit REST API, without the Firebase SDK. The ID token is used once, exchanged for a platform session, and never stored, as before. Mobile sends the verification and reset emails itself, in the user's language. Sign-up answers an existing email the same way as a new one.
2. **Database: Cloud SQL for PostgreSQL** in the Firebase project.
   * **Connection.** The backend connects with SQLAlchemy and asyncpg through the **Cloud SQL Python Connector** when `DATABASE_CLOUD_SQL_INSTANCE` is set. The connector reaches the instance's public IP over TLS, with an ephemeral certificate issued to the service account (role Cloud SQL Client), so no IP allow-list is needed. Railway has no fixed egress address on every plan. The connector is the optional `gcp` extra, installed in the container image.
   * **Schema.** Migrations run through the same connection path. Data Connect's GraphQL layer is not used.
   * **Extensions and hardening.** The required extensions (PostGIS, `citext`, `pg_trgm`, `unaccent`) are available on Cloud SQL. The RLS hardening still runs; the Supabase role revocations are skipped automatically, because those roles don't exist there.
   * **Region.** `us-east1`, next to Railway's US East region. The EU-region question for launch markets stays open (docs/11 §9).
3. **Media storage: Cloud Storage buckets in the same project**, through the existing S3-compatible port (ADR-0022), with configuration only.
   * **Endpoint.** Google's XML API accepts SigV4 with HMAC keys: `MEDIA_S3_ENDPOINT=https://storage.googleapis.com`, region `auto`, path-style URLs.
   * **Buckets.** The quarantine and private buckets stay private. The public bucket grants `allUsers` the Storage Object Viewer role, and `MEDIA_PUBLIC_BASE_URL=https://storage.googleapis.com/<public-bucket>`. Bucket names are global, so they get a project prefix.
4. **Push: FCM** through the Expo push service, which the backend already uses (docs/11 §1.9). This needs the FCM V1 service account key uploaded to EAS and the Android app's `google-services.json`.
5. **API hosting: Railway**, with two services from the same repository and Dockerfile (root directory `backend`, region US East):
   * `api`: the image's default command, health check `/health/live`, and pre-deploy command `alembic upgrade head`;
   * `worker`: start command `python -m app.worker`, with no public domain.

   Railway's config-as-code files are deprecated (new services can't use them; existing ones stop being read on 2026-12-01). So the services are configured in the dashboard, as listed in docs/11 §1.0, not in a `railway.json`.
6. **Migration.**
   * Both platforms work side by side until cutover. The backend accepts tokens from every configured issuer, and the apps pick the provider from build configuration (`EXPO_PUBLIC_IDENTITY_PROVIDER`, default Firebase when its key is set).
   * There are no real users yet, so no accounts are migrated. The Cloud SQL database is created by `alembic upgrade head` and the seed commands, not copied from Supabase.
   * The web app moves in the web workstream (its BFF adapter).

## Consequences

* **Costs.**
  * Cloud SQL and Cloud Storage need the Firebase **Blaze** plan; the Cloud SQL instance is billed while it runs.
  * Railway bills the plan fee plus usage, with two services.
  * Staff TOTP MFA needs the **Identity Platform** upgrade of Firebase Authentication, which is billed per monthly active user above its free tier.
* **Configuration in the Firebase console** (docs/11 §1.0):
  * a password policy of at least 8 characters;
  * email enumeration protection;
  * authorized domains;
  * email templates and their sender domain;
  * a Web API key restricted to the Identity Toolkit and Token Service APIs.
* **AUTH-005.** It is now driven by Firebase: any password change or reset, or an admin "revoke refresh tokens", ends older platform sessions at the next sign-in.
* **Supabase-specific code.** The Supabase Auth client, the `auth_hooks` migration and the Supabase Admin deleter stay until cutover, then go (BL-6.11).
* **Records of processing.** These change: Google becomes the processor for accounts, data, files and push (docs/15).
* **Social sign-in.** It is hidden in the apps while Firebase is the provider, until BL-6.12.

## Alternatives considered

* **Firestore:** rejected. It means a rewrite of the data layer and features breaking during the move.
* **Keep Supabase:** the owner chose Firebase.
* **Cloud Run instead of Railway:** native Cloud SQL sockets and one vendor, but the owner chose Railway.
* **Cloud SQL Auth Proxy sidecar:** a second process in each container. The in-process connector gives the same TLS and IAM model.
* **Public IP with an allow-list:** Railway's egress addresses are not fixed on every plan, and `0.0.0.0/0` with only a password is too exposed.
* **Firebase Admin SDK:** heavy for one call. The JWT-bearer grant and a REST call cover deletion.
