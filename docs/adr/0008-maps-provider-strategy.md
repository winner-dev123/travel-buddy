# ADR-0008: MapLibre + offline-licensable tiles; routing via provider

- **Status:** Proposed (needs a provider and licensing decision, PRD Q-3)
- **Date:** 2026-11-09
- **Requirements:** GUIDE-001..003, OFF-001
- **Related:** [ADR-0014](0014-web-maps-maplibre.md) (web uses MapLibre GL JS with the same tile provider)

## Context
Offline map regions are a core feature. Several commercial map SDKs restrict offline caching (Google Maps Platform terms generally prohibit storing tiles for offline use). Building a navigation engine is out of scope.

## Decision (proposed)
* Render with **MapLibre Native** (`@maplibre/maplibre-react-native`, open source).
* Tiles come from a provider whose license permits offline packs (MapTiler, Stadia Maps, or self-hosted OpenMapTiles/Protomaps **PMTiles** from OSM data with ODbL attribution). Region packs ship as PMTiles in offline packages.
* Walking route previews use a hosted routing API (Mapbox Directions, GraphHopper, or a Valhalla-based provider) behind a `RoutingProvider` port. Routes are previews only, not turn-by-turn navigation.
* Geocoding and place data come from a licensed provider behind a `PlacesProvider` port, storing attribution and freshness.

## Consequences
Vendor independence for rendering. Offline licensing is explicit and auditable. Self-hosted tiles add a build pipeline (Phase 4).
