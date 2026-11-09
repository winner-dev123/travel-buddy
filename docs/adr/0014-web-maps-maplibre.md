# ADR-0014 — MapLibre GL JS for web maps

* **Status:** Accepted (the tile vendor follows ADR-0008)
* **Date:** 2026-11-09
* **Related:** [doc 02 §14](../02-system-architecture.md#14-maps-guides-and-offline), [ADR-0008](0008-maps-provider-strategy.md)

## Context

The brief allows "Mapbox GL JS or a suitably licensed alternative". Doc 02 chose MapLibre Native on mobile, with a licensed vector-tile provider whose terms permit offline caching. Mapbox GL JS v2+ is proprietary and billed per map load.

## Decision

* Use **MapLibre GL JS** (BSD-3) on the web, with the same vector-tile provider and style as mobile. The style URL comes from `NEXT_PUBLIC_MAP_STYLE_URL`.
* The map is always dynamically imported (`ssr: false`) and mounted only when visible. This keeps about 250 KB gzip out of first-load bundles.
* Development without a provider key uses MapLibre's public demo style with a visible "Development map" label. Production builds fail the environment check if the style URL is unset.
* Marker clustering uses MapLibre's GeoJSON source clustering. Viewport-driven loading calls `GET /v1/destinations/{id}/places?bbox=`, debounced at 300 ms.
* Geocoding and autocomplete go through the platform (`/v1/destinations/search`), never directly from the browser to a geocoder with a secret key.

## Consequences

* One style and one vendor contract cover web and mobile. Offline map regions are a mobile/PWA concern and use PMTiles where the licence allows.
