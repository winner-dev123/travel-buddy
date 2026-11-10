# ADR-0022: Media object storage through an S3-compatible port

- **Status:** Accepted
- **Date:** 2026-11-09
- **Deciders:** Backend
- **Requirements:** POST-004, SAFE-004, T-MED-01..05

## Context

docs/02 §11 describes the media pipeline. Clients upload through presigned PUTs to a quarantine
bucket. A worker verifies and re-encodes each image, and the processed variants go to a public bucket
served through a CDN. The architecture only says "S3-compatible". We need a concrete store for
staging, which runs on Vercel serverless, and a way to develop and test without one.

## Decision

1. **Port with two adapters.** `ObjectStorage` covers presigned PUT, quarantine head/read/delete
   and public write/delete/URL.
   - `S3Storage` talks to any S3-compatible endpoint (AWS S3, Cloudflare R2, MinIO, and Supabase
     Storage's S3 endpoint). It signs with our own SigV4 implementation, pinned to AWS's published
     test vectors, so there's no SDK dependency.
   - `LocalStorage` keeps both buckets in process memory and serves them from a dev-only ASGI
     mount (`/_dev/storage`). It is allowed only in development and test. It emulates the external
     store, so it isn't part of the API contract.
2. **Recommended store: Supabase Storage.** We already use the Supabase project (ADR-0018), its S3
   endpoint works with SigV4 access keys, and public buckets come with a CDN URL.
   - `media-quarantine` is a private bucket. Set a file-size limit of 25 MB, raising it to 200 MB
     when video lands.
   - `media-public` is a public bucket. Its public URL is `MEDIA_PUBLIC_BASE_URL`.
   - This doesn't change ADR-0018's "Data API locked down": Storage is reached only by the backend
     with S3 keys, and clients only ever get presigned URLs.
3. **Upload rules.**
   - The presigned PUT signs `Content-Type` and `Content-Length`, so the store refuses any other
     type or size, and it expires after 5 minutes.
   - At processing time, the worker checks size, SHA-256 and magic bytes against the declaration.
   - Images are re-encoded to WebP at 1600, 800 and 320 px, with orientation applied and no
     EXIF/GPS or ICC data.
   - Rejected or abandoned uploads never reach the public bucket, and quarantine objects are
     deleted after processing.
   - HEIC and video are refused with `415` until a decoder and a transcoding service are chosen.
4. **Scanning port.** `MalwareScanner` currently has a no-op implementation. A real scanner and CSAM
   hash matching are required before launch (SAFE-004, T-MED-03).
5. **No storage configured → uploads answer `503`.** Everything else keeps working, so staging
   boots before the buckets exist.
6. **Private media (BL-3.05, added 2026-11-09).** Message attachments (purpose `message`) are
   processed the same way, but their variants go to a private bucket (`MEDIA_PRIVATE_BUCKET`,
   defaulting to the quarantine bucket, under `pm/`) and never to the public one. The owning module
   authorizes the viewer first (messaging checks membership), then the API returns a presigned GET
   that lives 5 minutes (`MediaRef.url_expires_at`). Deleting the message or the account deletes
   the private objects.

## Consequences

- One code path for every S3-compatible provider. Moving to R2 or AWS is a configuration change.
- Processing runs in the job queue. On serverless it happens in after-response or cron ticks and
  completes within seconds for photos. Large-video transcoding will need a managed service, not
  this worker.
- Account deletion queues deletion of every stored variant (the rows cascade with the user).
- The no-op scanner is a launch blocker that the backlog tracks explicitly.

## Alternatives considered

- **boto3 / aioboto3:** a heavy dependency and cold-start cost on serverless, for three operations.
- **Supabase Storage REST API (signed upload tokens):** simpler for Supabase alone, but it ties the
  media module to one vendor.
- **Uploading through the API:** doubles bandwidth and hits serverless request-size limits.
