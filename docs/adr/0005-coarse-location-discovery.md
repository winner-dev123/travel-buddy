# ADR-0005: Traveler discovery uses destinations, never coordinates

- **Status:** Accepted
- **Date:** 2026-11-09
- **Requirements:** DISC-001..004, DISC-009, LOC-003, LOC-009. Threats T-LOC-01..04

## Context
Nearby-people features are a known vector for stalking. Even "fuzzed" coordinates or rounded distances leak position through trilateration and repeated sampling. The requirements forbid exposing precise coordinates and exact distances.

## Decision
* Discovery is scoped to a **destination** (city, or neighborhood if the user chooses that granularity). A discovery session stores `destination_id` and optional `area_destination_id`, and **no coordinate column exists**.
* If the user uses GPS, the server resolves the point to a destination via PostGIS (`ST_Covers` on destination boundaries) and discards the point in the same request.
* The discover endpoint accepts a destination, never a point and radius. Responses contain area labels only, no distance.
* Sessions are opt-in, TTL ≤ 72 h, purged 30 days after end. Invisible mode neither shows nor browses.

## Consequences
* Trilateration is impossible by construction, and the stored data is low-sensitivity.
* "Within 500 m" style features are impossible. That is accepted as product policy.
* Neighborhood boundaries must exist for launch cities when neighborhood granularity is offered.

## Alternatives considered
* **Geohash or H3 cells with jitter**: still leaks under repeated sampling, and cell boundaries reveal more than administrative areas.
* **Distance buckets ("< 1 km")**: enables trilateration with multiple vantage points.
