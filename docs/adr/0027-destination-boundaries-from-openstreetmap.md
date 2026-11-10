# ADR-0027: Destination boundaries from OpenStreetMap relations

- **Status:** Accepted
- **Date:** 2026-11-10
- **Deciders:** Backend
- **Requirements:** DEST-005, LOC-005, LOC-008, DISC-003

## Context

Point resolution (`ST_Covers`) decides which city a device is in: the Nearby feed, discovery's
city and neighbourhood, and the `resolve` endpoint all depend on it. The launch catalog shipped
with approximate bounding boxes, so points near a city's edge resolve to the wrong place, and
DEST-005 asks for boundaries loaded from OpenStreetMap or geoBoundaries with their license
recorded. ADR-0025 already uses OpenStreetMap (ODbL) for places.

## Decision

1. **Source: OSM administrative boundary relations through the Overpass API** (ODbL 1.0,
   "© OpenStreetMap contributors"), the same provider and license as places. geoBoundaries covers
   countries and their administrative levels well but not cities and neighbourhoods consistently.
2. **Assembly.** The relation's `outer` and `inner` ways are joined end to end into closed rings,
   each hole goes into the outer ring that contains it, and PostGIS repairs the result
   (`ST_MakeValid`, polygons only, `ST_Multi`). Code: `destinations/boundaries.py`.
3. **Recorded license.** `destination_boundaries.source` is `osm:<relation id>`;
   `BOUNDARY_LICENSES` maps the prefix to `ODbL-1.0`. The seed's boxes keep `approximate-bbox`.
4. **Operator command, not request time.** `python -m app.modules.destinations.boundary_ingestion
   --destination <path> --relation <id>` (or `--all` for seed entries that name an
   `osm_relation_id`) loads polygons, pausing between Overpass calls. Re-seeding the catalog never
   overwrites a polygon from another source.
5. **Scope.** Cities and neighbourhoods first: they decide Nearby and discovery. Countries may keep
   their boxes, because the most specific (deepest) match wins.

## Consequences

- ODbL share-alike applies to the boundary table as to places (ADR-0025): it stays separable by
  `source` from any future commercial data.
- Each relation ID is chosen by a person and checked on a map before loading (the launch
  playbook's catalog step); a wrong relation would misplace everyone near that city.
- Overpass is rate-limited; large loads need a self-hosted instance or a planet extract.

## Alternatives considered

- **Keep bounding boxes:** simple, but wrong near edges and between neighbouring cities.
- **geoBoundaries (CC BY 4.0):** good for countries; city and neighbourhood levels vary by country.
- **Commercial boundaries:** not justified at launch scale.
