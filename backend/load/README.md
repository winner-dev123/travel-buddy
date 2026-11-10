# Load and soak tests (BL-6.04)

[k6](https://k6.io) scenarios against a **staging** stack. The thresholds come from the PRD's
non-functional requirements; a run fails when they are missed.

| Script | What it does | Thresholds |
|---|---|---|
| `api-mix.js` | Ramps virtual users through the feed, posts, comments and unread counts; one iteration in ten writes a post and a reaction | reads p95 < 300 ms, writes p95 < 500 ms, feed p95 < 300 ms (NFR-001); errors < 1 % |
| `soak.js` | A constant arrival rate for hours (`/users/me`, conversations, groups) | p95 < 300 ms, p99 < 1 s, errors < 0.1 % (NFR-003) |

## Rules

* Never run these against production. `lib.js` refuses `*.travelbuddy.app` hosts unless
  `I_HAVE_APPROVAL=yes` is set, and that needs a written go-ahead and a maintenance window.
* Load costs money (Vercel, Supabase compute, egress): agree the window and size first.
* Writes create real rows: use a disposable staging database, or clean up afterwards
  (posts whose body starts with `Load test tip`).
* Set the rate-limit store for staging so the limits under test are the production ones. A run
  dominated by `429`s measures the rate limiter, not the API.

## Running

```bash
# Development or staging with the dev IdP enabled: users are created on the fly.
k6 run -e BASE_URL=https://api.staging.example -e VUS=50 -e HOLD=10m backend/load/api-mix.js

# Staging without the dev IdP: pass pre-issued access tokens of test accounts.
k6 run -e BASE_URL=https://api.staging.example -e TOKENS="$TOKENS" backend/load/soak.js
```

| Variable | Default | Meaning |
|---|---|---|
| `BASE_URL` | `http://localhost:8000` | API origin |
| `VUS`, `RAMP`, `HOLD` | `50`, `2m`, `5m` | `api-mix.js` shape |
| `RATE`, `DURATION`, `VUS`, `MAX_VUS` | `20`, `2h`, `40`, `200` | `soak.js` shape |
| `TOKENS` | – | comma-separated access tokens (one per virtual user, reused round-robin) |
| `DESTINATION_PATH` | `portugal/lisbon` | destination whose feed is read |
| `TERMS_VERSION`, `PRIVACY_VERSION` | `2026-11-01` | legal versions accepted when the dev IdP registers users |
| `THINK_SECONDS` | `1` | pause between iterations |

## Chaos drills

Run `soak.js` and, during it:

1. **Redis loss** (when Redis backs rate limits or realtime): stop it for five minutes. The API
   must keep answering (rate limiting falls back as configured in `RATE_LIMIT_STORE`), realtime
   clients reconnect, and nothing is lost: messages are in Postgres and the outbox relays them.
2. **Realtime node loss**: kill one realtime process. Clients reconnect to another node and
   resync from their last `seq`.
3. **Worker loss**: stop the workers for ten minutes, then start them. `GET /v1/admin/ops/summary`
   shows the outbox and job backlog grow and drain; no job runs twice to visible effect
   (idempotent handlers, dedupe keys).

Record the results (p95/p99, error rate, backlog peaks and drain time) in
`docs/11-infrastructure-deployment.md` (load results) next to the date and the stack size.
