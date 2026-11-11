# ADR-0029: Supabase free tier for the database and media; Firebase for identity and push

- **Status:** Accepted
- **Date:** 2026-11-11
- **Deciders:** Product owner ("my current tight financial situation"; chose "Supabase free" over Google Drive and paid Google storage), backend
- **Requirements:** NFR-003, NFR-004, POST-004, SAFE-004, SAFE-010
- **Amends:** [ADR-0028](0028-firebase-platform-and-railway-hosting.md): its database (Cloud SQL) and media (Cloud Storage) parts are replaced. Firebase Auth, FCM and Railway stay.
- **Reinstates:** [ADR-0018](0018-supabase-managed-postgres.md) (Supabase PostgreSQL) and the Supabase Storage option of [ADR-0022](0022-media-object-storage.md)

## Context

ADR-0028 moved everything to Firebase. Its database (Cloud SQL) has no free tier, and Cloud Storage needs the Blaze plan with a card. The owner can't pay for either now and proposed storing photos in a free personal Google Drive.

Google Drive was rejected as the media store:
* Drive throttles frequently viewed files and is no CDN.
* Drive doesn't fit the presigned-upload, server-processed pipeline (EXIF stripping, WebP renditions, private chat photos).
* Drive would put travellers' photos in the owner's personal account, with no processing agreement.

The Supabase project from ADR-0018 already exists on the free plan. Its database is current (migrations, PostGIS, the launch catalog), and its Storage speaks the S3 protocol the media port already uses.

## Decision

* **Database:** Supabase PostgreSQL (free plan). The Railway services connect through the **session pooler** (`aws-0-us-east-1.pooler.supabase.com:5432`, `?ssl=require`, `DATABASE_TRANSACTION_POOLER=false`), with small pools (API 3 + 2 overflow, worker 3) to stay within the free plan's connections.
* **Media:** Supabase Storage through its S3 endpoint (`https://<ref>.storage.supabase.co/storage/v1/s3`, region `us-east-1`).
  * Buckets `media-quarantine` (private; uploads and private chat photos) and `media-public` (public renditions) both take JPEG, PNG and WebP up to 25 MB.
  * `MEDIA_PUBLIC_BASE_URL` is the bucket's public object URL.
  * The S3 access key is server-only, in Railway variables.
* **Identity and push:** Firebase Auth and FCM, as in ADR-0028 (free). Supabase Auth is no longer the provider; its acceptance on staging ends with the cutover.
* **Hosting:** Railway, as in ADR-0028.

## Consequences

* **Cost.** The platform costs $0 apart from Railway's plan, which runs about $5 a month after the trial.
* **Free-plan limits:** a 500 MB database, about 1 GB of files, limited egress, and a project paused after a week without activity. The worker's regular queries keep it active.
* **Backups.** The free plan has no point-in-time recovery (NFR-004 stays open until a paid tier or another backup routine).
* **Moving later.** Moving the database (Cloud SQL or Supabase Pro) or media (Cloud Storage, R2) later needs only settings, because the code already supports all of them.
* **Records of processing.** Supabase is again the processor for data and files; Google for sign-in and push (docs/15).

## Alternatives considered

* **Google Drive:** rejected (above).
* **Google Cloud Storage free tier (5 GB):** needs a card on file, and the database would still cost money.
* **Railway PostgreSQL:** it would count against Railway usage. It also lacks PostGIS unless a PostGIS template is run as another always-on service.
