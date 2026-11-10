# 16. Destination launch playbook

How to open a new destination (usually a city) to travellers: what to prepare, the commands,
the go/no-go check, and how to roll back (BL-6.08). Every step is repeatable: the loaders are
idempotent and safe to run again.

**Roles:** *Launch owner* (one person, runs the checklist), *Content* (copy, guides, editorial
stories), *Trust & safety* (moderation cover, local safety copy), *Engineering on call*
(commands, monitoring). A role can be one person in a small team.

## 1. Is the destination ready to launch?

| Criterion | Why | Check |
|---|---|---|
| Market cleared | Each market needs a legal review of age policy, prizes and data transfers (PRD §10) | Legal sign-off recorded in the launch ticket |
| Moderation covers the local language | Reports must be handled within 24 hours (SAFE-003; App Store 1.2) | Rota names someone who reads the language |
| Enough content to avoid an empty feed | The feed falls back to wider sources when a destination is thin (`context.source` moves from `gps` or `selected` to `interests`, then `global`), which feels generic to new users | At least 30 editorial stories and 1 free guide per launch locale planned |
| Places available | Recommendations, trips and guides refer to catalog places (DEST-003) | OpenStreetMap coverage inside the planned radius looks complete |

## 2. Timeline

| When | Step | Owner |
|---|---|---|
| T−6 weeks | Go/no-go on the criteria above; open the launch ticket | Launch owner |
| T−4 weeks | Catalog entry and places loaded on staging (§3.1, §3.2) | Engineering |
| T−4 weeks | Names and taglines in all five languages reviewed by native speakers | Content |
| T−3 weeks | Guides and audio tours written and loaded on staging (§3.3) | Content |
| T−2 weeks | Safety: brief moderators on local risks and scams; review the Safety center copy (SCR-114 is bundled in the apps, so a change ships with an app release) | Trust & safety |
| T−2 weeks | Editorial stories drafted (staff or creator accounts, real photos with rights) | Content |
| T−1 week | Full check on staging (§4); production load with the destination **hidden** (§3.4); offline packages built (§3.5) | Engineering |
| T−1 week | Moderation rota confirmed; creator programme invites sent | Trust & safety, Content |
| T−0 | Go/no-go on the staging result, then unhide and feature (§3.6) and the production smoke check | Launch owner |
| T+1 day, T+1 week, T+4 weeks | Review the launch metrics (§5) | Launch owner |

## 3. Commands

Run from `backend/` with the target environment's settings (`DATABASE_URL` and storage settings
in the environment). Staging first, always; production only after the staging result has been
checked in the app.

### 3.1 Catalog entry

Add the destination to a catalog file (same format as
`app/modules/destinations/seed/launch_destinations.json`): `path` (`country/city`), `kind`,
`country_code`, `continent`, `time_zone`, `centroid`, `bbox`, `names` and `taglines` in en, es,
pt-BR, fr, de, optional `alt_names` and `featured: false`. Bounding boxes are approximate; use
licensed polygons where edge accuracy matters (nearby resolution near borders).

```bash
python -m app.modules.destinations.seeding --file path/to/catalog.json
```

The loader upserts by slug and replaces localizations and the boundary: re-running it after a
copy fix is safe.

### 3.2 Places

```bash
python -m app.modules.destinations.place_ingestion --destination country/city --radius 6000
```

Reads public places around the centroid from OpenStreetMap (ODbL; attribution is shown in the
apps) and upserts them by provider id. For curated lists use `--file` with a places document.
Re-run monthly to refresh freshness.

### 3.3 Guides and audio tours

```bash
python -m app.modules.guides.seeding --file path/to/guides.json
```

Validates every section before writing, publishes each guide by `(destination, locale, slug,
version)` and retires older versions. Each guide needs `content_license` (and `attribution` when
the license requires it). At least one `free` guide per launch locale.

### 3.4 Hidden first

New catalog entries are active. On production, hide the destination right after loading, so
nobody finds it before the launch:

```http
PATCH /v1/admin/destinations/{id}
X-Audit-Justification: Launch prep for <city>: hidden until go/no-go
{"status": "hidden"}
```

Hidden destinations drop out of every public read (search, lists, destination pages, feeds),
so the full check (§4) runs on staging, where the destination stays active.

### 3.5 Offline packages

```bash
python -m app.modules.guides.packaging --destination country/city
```

One signed package per locale with guides, in private storage (needs `MEDIA_STORAGE=s3` and the
offline signing key). Unchanged content keeps its version; changed content becomes the next
version. Re-run after every guide change.

### 3.6 Launch

```http
PATCH /v1/admin/destinations/{id}
X-Audit-Justification: <city> launch approved in <ticket>
{"status": "active", "is_featured": true}
```

Featuring puts the destination in the featured lists (`GET /v1/destinations/featured`, for
example the web home page). Both changes purge the cached web pages within seconds (the
`destination_changed` revalidation webhook). Remove the feature after the launch campaign
(usually 4 weeks).

Right after unhiding, smoke-check production (15 minutes): the destination opens in the app,
search finds it, its feed shows the editorial stories and the web page renders. On any failure,
hide it again (§6).

Feature flags are global, not per destination: do not turn on a flag (for example
`traveler_discovery`) as part of a city launch. Discovery in the EU needs the approved DPIA
(docs/13).

## 4. Go/no-go checklist (on staging, T−1 week to T−0)

- [ ] Destination opens in the app in all five languages (name, tagline, guides list).
- [ ] Search finds it by its local and English names; nearby resolution picks it inside the city.
- [ ] Feed for the destination shows editorial stories with `context.source = selected`.
- [ ] Free guide opens; offline package downloads and plays in airplane mode.
- [ ] Places in recommendations and trip planning look right (spot-check 20).
- [ ] Safety center copy in the current app release covers the market.
- [ ] Moderation rota covers the first two weeks, including weekends; the report queue is empty.
- [ ] `GET /v1/admin/ops/summary`: no dead jobs, outbox lag under a minute.
- [ ] Web public pages: the destination page and lists render; hiding and unhiding it on staging
      updates them within seconds.

If any box is unchecked, postpone: on production the destination stays hidden with no user
impact.

## 5. After launch

| Signal | Where | Act when |
|---|---|---|
| Stories per day in the destination | Admin web dashboards (BL-6.02) / database | Under 5 a day after week 1: more editorial content, creator outreach |
| Feed fallbacks (`context.source` other than `selected` for the destination) | Feed logs | Rising after week 2: content gap |
| Open reports and oldest report age | `GET /v1/admin/ops/summary` | Oldest open report near 24 hours |
| Search misses for local names | Search logs | Add `alt_names` and re-run the catalog loader |
| Guide downloads and offline licences | Database | No downloads after week 2: check the guide's placement and language |

## 6. Rollback

1. Hide the destination (`{"status": "hidden"}`, §3.4). It leaves search, lists, feeds and
   public pages at once, and the cached web pages are purged.
2. User content stays: posts that named the destination are neither changed nor deleted and
   remain on their authors' profiles (the hidden destination is left out of their summaries).
3. Record the reason in the launch ticket. Re-launch with the full checklist.

To remove a catalog entry for good (a duplicate, a mistake), hide it and plan a data migration
that moves references to the right destination. The loaders never delete destinations.
