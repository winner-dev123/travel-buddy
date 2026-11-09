# Terraform

Cloud-neutral module layout per [docs/11 §4](../../docs/11-infrastructure-deployment.md#4-terraform-layout). **No resources are defined yet.** The cloud provider decision is open (PRD Q-8), and staging infrastructure is first needed for Phase 1 preview environments.

```
infra/terraform/
  modules/
    network/        # VPC, subnets, NAT, security groups
    database/       # PostgreSQL 16 + PostGIS, backups (PITR), replicas
    cache/          # Redis
    storage/        # buckets: quarantine (24 h expiry) / public / private; CDN
    service/        # generic container service: image, command, env, secrets, autoscaling
    secrets/        # secret containers (values set out of band, never in state or tfvars)
    observability/  # log groups, dashboards, alerts (docs/11 §8)
  envs/
    staging/
    production/
```

Rules:

* Remote state is encrypted, locked, and kept in one state per environment.
* CI authenticates with OIDC federation (no long-lived keys). `plan` runs on PR and `apply` requires manual approval.
* Module interfaces are provider-neutral (inputs like `cpu`, `memory`, `min_replicas`, `secrets`). Provider-specific implementations live behind them. AWS is the reference implementation (docs/11 §2).
