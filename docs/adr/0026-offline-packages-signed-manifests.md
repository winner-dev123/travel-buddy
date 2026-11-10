# ADR-0026: Offline packages with signed manifests and tokenized downloads

- **Status:** Accepted
- **Date:** 2026-11-10
- **Deciders:** Backend, Mobile
- **Requirements:** OFF-001, OFF-004, OFF-005, GUIDE-004

## Context

Travellers download guides (and later audio tours and map regions) to use without connectivity.
Downloads must be:

- verifiable, so a corrupted or tampered file is detected and fetched again (OFF-001);
- limited by entitlement, with free accounts getting 1 package and premium 15 (OFF-004);
- disabled when the content license expires (OFF-005).

Files can be large and are fetched by download managers that cannot attach our bearer token. Media
already lives in S3-compatible storage (ADR-0022) with presigned URLs, which cannot be issued for a
whole prefix.

## Decision

1. **Packages are built ahead of time** by an operator command (`python -m app.modules.guides.packaging`).
   A `guide` package holds a destination's published guides in one locale as JSON files, an index and
   the catalog places they mention. It is written to private storage under `offline/<package id>/`.
   Unchanged content keeps its published version; changed content becomes version N+1, and the previous
   version is retired.
2. **Manifests are signed with Ed25519 when issued.** The signature covers canonical JSON (sorted keys,
   no whitespace, UTF-8) of the manifest without its `signature` field: package, version, files with
   sizes and SHA-256, the file-list hash, the license expiry and `issued_at`. The signing key
   (`OFFLINE_MANIFEST_PRIVATE_KEY`) is separate from the session-token key. Its public half is
   published in `GET /v1/client-config` under `offline_manifest_keys`, matched by `key_id`, so keys
   can rotate without an app release. Without a key, licensing and manifests answer 503 outside
   development.
3. **Licenses are per user, package and device.** Re-licensing is idempotent and free. Licensing a
   newer version on a device replaces the older license without using quota. Otherwise, active
   licenses count against `offline.packages`, under a per-user advisory lock. Premium packages also
   need the content entitlement.
4. **Downloads use a token URL.** `download.base_url` is `/v1/offline-downloads/{token}/`, with an
   HMAC token that names one license and expires after six hours. Each file request re-checks that
   the license is active and the package is not past `license_expires_at`, then redirects (307) to a
   short-lived presigned storage URL. Released licenses and expired content stop downloading at
   once.

## Consequences

- The client verifies the manifest signature, then each file's SHA-256, and compares `version` to
  detect updates. A file that fails is downloaded again.
- Expiry is enforced at license, manifest and download time. Already-downloaded content must also
  be disabled on the device after `license_expires_at`.
- Builds need shared object storage, because the development store lives in the API process.
- The download route takes no bearer token: the token is the credential, so it must stay out of
  logs and analytics.

## Alternatives considered

- **One presigned URL per file in the license response:** this lists every URL up front and they
  expire mid-download for large packs. A token prefix stays valid and is re-checked per file.
- **Serving files through the API:** this ties up serverless functions with large transfers.
  Redirecting to storage keeps the API out of the data path.
- **Reusing the session-token signing key:** one compromise would cover two protocols, and keys
  could not rotate independently.
