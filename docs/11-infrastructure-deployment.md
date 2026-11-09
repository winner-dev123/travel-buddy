# 11 — Infrastructure and Deployment Plan

| | |
|---|---|
| **Status** | Draft v1.0 — Phase 0 |
| **Principle** | Managed services where practical. Cloud vendor kept configurable until deployment constraints are final (PRD Q-8). The Terraform layout is vendor-neutral at the module interface; the first concrete implementation targets AWS as the reference, and GCP/Azure equivalents are listed |

## 1. Environments

| Env | Purpose | Data | Deploy trigger |
|---|---|---|---|
| `local` | Developer loop | Synthetic | `docker compose up` |
| `ci` | Automated tests | Synthetic, ephemeral | Every push / PR |
| `preview` (Phase 1+) | Per-PR full stack | Synthetic seed | PR label `preview` |
| `staging` | Release candidate, store sandbox, IdP test tenant | Synthetic + test accounts | Merge to `main` |
| `production` | Live | Real | Manual approval of a tagged release |

## 2. Runtime topology (production reference)

```mermaid
flowchart TB
  U[Users] --> CDN[CDN + WAF]
  CDN --> LB[Load balancer<br/>HTTP + WebSocket]
  LB --> API[api service<br/>autoscale on CPU/RPS]
  LB --> RT[realtime service<br/>autoscale on connections<br/>sticky not required]
  API --> PGP[(Postgres primary<br/>Multi-AZ, PITR)]
  API --> PGR[(Read replica<br/>Phase 6+)]
  RT --> PGP
  API --> RC[(Managed Redis<br/>cluster mode off, Multi-AZ)]
  RT --> RC
  WK[worker service<br/>autoscale on queue depth] --> PGP
  WK --> RC
  WK --> S3[(Object storage<br/>quarantine / public / private)]
  SCH[scheduler<br/>1 replica, leader lock] --> PGP
  S3 --> CDN
  API --> SM[Secret manager]
  WK --> SM
  OTEL[OTel collector] --> OBS[Logs / metrics / traces backend]
  API -.-> OTEL
  RT -.-> OTEL
  WK -.-> OTEL
```

| Component | AWS (reference) | GCP | Azure |
|---|---|---|---|
| Containers | ECS Fargate (or EKS when > ~15 services) | Cloud Run / GKE | Container Apps / AKS |
| Postgres + PostGIS | **Supabase (chosen, ADR-0018)**: project `us-east-1`, Free plan now, Pro + PITR before real user data. Alternatives: RDS for PostgreSQL | Cloud SQL for PostgreSQL | Azure Database for PostgreSQL Flexible |
| Redis | ElastiCache for Redis | Memorystore | Azure Cache for Redis |
| Object storage + CDN | S3 + CloudFront | GCS + Cloud CDN | Blob Storage + Front Door |
| Secrets | Secrets Manager + KMS | Secret Manager + KMS | Key Vault |
| WAF | AWS WAF | Cloud Armor | Front Door WAF |
| Email (transactional) | IdP-managed / SES | IdP / SendGrid | IdP / ACS |
| Malware scan | ClamAV container (worker sidecar) | Same | Same |

## 3. Containers

One backend image (`backend/Dockerfile`, multi-stage, non-root, read-only root filesystem, distroless/slim runtime) runs with different commands per process role:

| Service | Command | Min/Max replicas (launch) | Health |
|---|---|---|---|
| api | `uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers` | 2 / 20 | `/health/live`, `/health/ready` |
| realtime | `uvicorn app.realtime_main:app --port 8001` | 2 / 20 | `/health/live` |
| worker | `python -m app.worker` | 1 / 20 | Heartbeat row + liveness file |
| scheduler | `python -m app.worker --role scheduler` | 1 / 1 | Leader lock metric |

Database migrations run as a **one-off task** before the new version is rolled out (`alembic upgrade head`). Migrations must be backward-compatible with the previous release (expand → migrate → contract), so rolling deploys never break running pods.

## 4. Terraform layout

```
infra/terraform/
  modules/
    network/         # VPC, subnets, NAT, security groups
    database/        # Postgres + PostGIS, parameter group, backups, replicas
    cache/           # Redis
    storage/         # buckets (quarantine/public/private), lifecycle rules, CDN
    service/         # generic container service (image, cmd, env, secrets, autoscaling)
    secrets/         # secret containers (values set out of band)
    observability/   # log groups, dashboards, alerts
  envs/
    staging/         # composition of modules + tfvars (no secrets)
    production/
```

* Remote state in an encrypted bucket with state locking. One state per environment.
* CI uses OIDC federation to the cloud (no long-lived keys). `terraform plan` runs on PRs touching `infra/`, and `apply` requires manual approval.
* Bucket lifecycle: `quarantine` objects expire after 24 h. `private` attachments follow message retention. Versioning is on for `public` and `private`.

## 5. CI/CD pipeline

```mermaid
flowchart LR
  PR[Pull request] --> L[Lint + type<br/>backend & mobile]
  PR --> T[Tests<br/>unit/integration/security/contract]
  PR --> C[Contracts<br/>OpenAPI + realtime schemas]
  PR --> SEC[Secret scan<br/>+ dependency audit]
  L & T & C & SEC --> M[Merge to main]
  M --> B[Build + sign image<br/>SBOM]
  B --> STG[Deploy staging<br/>migrate → roll]
  STG --> SM[Smoke + E2E nightly]
  SM --> TAG[Tag release]
  TAG --> APR{Manual approval}
  APR --> PRD[Deploy production<br/>migrate → canary 10% → 100%]
```

Mobile: EAS Build for store binaries (`development`, `preview`, `production` profiles). OTA updates through EAS Update **only** for JS-only fixes that are compatible with the native runtime, with a runtime-version policy. Store submissions go through EAS Submit after manual QA.

## 6. Configuration and secrets

* 12-factor configuration through environment variables, typed and validated at boot (`app/core/config.py`). Boot fails fast on invalid configuration.
* Secrets (DB password, JWT signing keys, IdP client secrets, store credentials, AI keys) live only in the secret manager, are injected at runtime, and are rotated on a schedule (JWT keys support multiple active `kid`s for rotation).
* `APP_ENV=production` boot guard: development adapters (dev IdP, dev billing, fake push, stub AI) cause startup failure.

## 7. Data protection and recovery

| Control | Setting |
|---|---|
| Postgres backups | Supabase: **none on the Free plan**. Pro gives daily backups (7 days). The PITR add-on gives RPO ≤ 5 min. Upgrade before any real user data (ADR-0018) |
| Restore drill | Quarterly, documented time-to-restore (RTO target ≤ 1 h) |
| Encryption | At rest (KMS) for DB, Redis, buckets. TLS 1.2+ in transit, including DB connections |
| Object storage | Versioning on public/private. Replication to a second region (Phase 6) |
| Audit logs | Monthly partitions exported to WORM storage (object lock) |

## 8. Observability and alerting

| Signal | Alert |
|---|---|
| API 5xx rate | > 1 % for 5 min |
| API p95 latency | > 500 ms for 10 min |
| Outbox lag | Oldest unpublished > 60 s |
| Job queue | Oldest queued > 5 min (per queue). Dead jobs > 0 for billing queue |
| Realtime | Connection drop rate spike. Fanout lag > 2 s |
| Billing webhooks | Processing failures > 0 |
| Moderation | Priority report unassigned > 1 h |
| AI | Daily spend > budget × 0.8 |

SLOs: API availability 99.9 %, message delivery p95 < 500 ms. Error budgets are reviewed monthly.

## 9. Regional strategy

Launch in a single region close to the core markets (an EU region, for GDPR and proximity to EU/UK, with acceptable latency to Brazil through the CDN), with the CDN serving media globally. Phase 7 evaluates a second region (Americas) with read replicas and regional realtime. That needs write-routing design and is deliberately deferred.

## 10. Cost guardrails

Budgets and alerts per environment. Staging scales to zero off-hours. Media size limits and CDN caching. AI spend circuit breaker. Log retention 30 days hot, 1 year cold.
