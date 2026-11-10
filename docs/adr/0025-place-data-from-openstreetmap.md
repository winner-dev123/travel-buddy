# ADR-0025: Place data from OpenStreetMap behind a `PlaceSource` port

- **Status:** Accepted
- **Date:** 2026-11-10
- **Deciders:** Backend
- **Requirements:** DEST-003, LOC-009, AI-003, AI-004

## Context

Itineraries, posts and trips reference public places (attractions, restaurants, viewpoints…).
DEST-003 asks for licensed data with attribution and freshness, and for stale provider data to be
flagged. AI itineraries must be grounded on catalog places (AI-003), and opening hours or other
details may only come from licensed sources, never from the model (AI-004). No commercial places
contract exists yet, and the catalog must work on plain PostgreSQL for local tests, as destinations
already do.

## Decision

1. **Port.** `destinations.place_sources.PlaceSource.fetch(lat, lng, radius_m, limit) -> SourceBatch`
   returns places together with the provider, license, attribution text and URL, and the time the
   source was read. Ingestion (`places.ingest`) upserts by `(provider, provider_place_id)`, stores
   `data_freshness_at`, replaces localized names, and keeps an editorial `hidden` status across
   re-ingestion. New places join the ingested destination.
2. **First source: OpenStreetMap through the Overpass API** (`OverpassSource`, ODbL 1.0,
   "© OpenStreetMap contributors"). OSM tags map to the catalog categories. Only published
   attributes we show (opening hours, website, phone, wheelchair, cuisine, Wikidata) are kept. A
   Wikidata link or website is a popularity hint. `DocumentSource` loads the same shape from JSON
   (curated seeds and tests). Loading runs as an operator command,
   `python -m app.modules.destinations.place_ingestion --destination <path>`.
3. **Storage without PostGIS.** As with destination centroids, positions are `lat`/`lng` doubles
   with a b-tree index. Nearby search filters on a bounding box first, then on haversine distance
   in SQL. Search uses trigram indexes on `f_unaccent(lower(name))` (migration 0031). This deviates
   from the ERD's `geography(Point)` column.
4. **Freshness.** `Place.data_stale` is true when the data is older than 180 days (DEST-003).
   Provider attributes are always returned with `data_freshness_at`. AI proposals carry each
   place's freshness and the oldest one in `freshness.catalog_data_as_of`. The prompt gets only
   place IDs, names and categories, never attributes.
5. **Visibility.** Nearby and search list only `active` places. `closed_permanently` places stay
   readable by ID, and `hidden` places (taken down) answer 404. Itinerary items may reference only
   active places, and deleting a place nulls the reference.

## Consequences

- Every surface showing places must show the attribution (`Place.attribution`), and OSM's is
  required by the license.
- ODbL share-alike: the OSM-derived rows form a derivative database. If they are distributed
  publicly as a database, they must be offered under ODbL. Each row has exactly one `provider`, so
  OSM data stays separable from any future commercial provider's data.
- The Overpass public instance is rate-limited, so ingestion is a deliberate operator or job
  action, not a request-time call. A heavier load would need a self-hosted Overpass or a planet
  extract.
- A commercial provider (richer hours, photos, popularity) becomes another `PlaceSource` adapter
  without schema changes.

## Alternatives considered

- **Google Places:** its terms forbid storing most content beyond short caching, which conflicts
  with offline packs and AI grounding.
- **A commercial POI license now:** deferred until the product and budget justify it. The port
  keeps it a drop-in addition.
- **A PostGIS `geography` column:** local tests and some environments run without PostGIS, and
  bounding-box plus haversine queries are enough at catalog scale.
