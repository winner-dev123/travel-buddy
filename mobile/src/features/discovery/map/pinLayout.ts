import type { GeoPoint } from './mapPage';

/**
 * Where to draw each traveller (DISC-004, DISC-012, ADR-0005, ADR-0030).
 *
 * The API never says where anyone is, only the city or neighbourhood they share. Each pin is
 * placed around that area's public centre, on a spiral ordered by a hash of the traveller's id,
 * so pins don't overlap; pins of nearby areas are then pushed apart. The spot therefore carries no
 * information beyond the area label, and the map says so.
 */

/** How far from an area's centre pins are spread, in metres. */
export const SPREAD_M = {
  city: { min: 800, max: 2200 },
  neighborhood: { min: 120, max: 420 },
} as const;

/**
 * Pins of nearby areas (a city and a neighbourhood 1.5 km from its centre) can land on each other.
 * Each pin keeps this distance from the others where it can, about one avatar at the city view.
 */
export const SEPARATION_M = 600;
/** How much further out than its spread a pin may be pushed to make room. */
export const MAX_PUSH_M = { city: 800, neighborhood: 900 } as const;
const PUSH_STEP_M = 150;
const PUSH_TURN = 0.9;

/** The circle the map shows around a city before a search: the city spread plus a margin. */
export const CITY_VIEW_RADIUS_M = 3200;
export const COUNTRY_VIEW_RADIUS_M = 350_000;

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
const METRES_PER_DEGREE = 111_320;

export interface PlacedTraveller {
  id: string;
  /** The area the traveller shares: its id and whether it's a city or a neighbourhood. */
  anchorId: string;
  anchorKind: keyof typeof SPREAD_M;
}

/** FNV-1a: a small, stable hash; not for security. */
export function stableHash(text: string): number {
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash >>> 0;
}

function byHash(a: PlacedTraveller, b: PlacedTraveller): number {
  return stableHash(a.id) - stableHash(b.id) || a.id.localeCompare(b.id);
}

function offset(centre: GeoPoint, radius: number, angle: number): GeoPoint {
  return {
    lat: centre.lat + (radius * Math.cos(angle)) / METRES_PER_DEGREE,
    lng:
      centre.lng +
      (radius * Math.sin(angle)) /
        (METRES_PER_DEGREE * Math.max(0.05, Math.cos((centre.lat * Math.PI) / 180))),
  };
}

/** Distance in metres (equirectangular: fine at city scale). */
export function metresBetween(a: GeoPoint, b: GeoPoint): number {
  const y = (a.lat - b.lat) * METRES_PER_DEGREE;
  const x = (a.lng - b.lng) * METRES_PER_DEGREE * Math.cos((b.lat * Math.PI) / 180);
  return Math.hypot(x, y);
}

/** Each traveller's map position, keyed by id. Travellers whose area centre is unknown are left out. */
export function layoutPins(
  travellers: readonly PlacedTraveller[],
  centres: ReadonlyMap<string, GeoPoint>,
): Map<string, GeoPoint> {
  const groups = new Map<string, PlacedTraveller[]>();
  for (const traveller of travellers) {
    const group = groups.get(traveller.anchorId) ?? [];
    group.push(traveller);
    groups.set(traveller.anchorId, group);
  }
  const spots: { traveller: PlacedTraveller; centre: GeoPoint; radius: number; angle: number }[] =
    [];
  for (const [anchorId, group] of groups) {
    const centre = centres.get(anchorId);
    if (!centre) continue;
    const ordered = [...group].sort(byHash);
    const start = (stableHash(anchorId) / 0xffffffff) * 2 * Math.PI;
    ordered.forEach((traveller, index) => {
      const spread = SPREAD_M[traveller.anchorKind];
      const share = Math.sqrt((index + 0.5) / ordered.length);
      spots.push({
        traveller,
        centre,
        radius: spread.min + (spread.max - spread.min) * share,
        angle: start + index * GOLDEN_ANGLE,
      });
    });
  }
  // Second pass, in an order that depends only on who is there: a pin too close to one already
  // placed moves outward and around its own area's centre until it is clear (or the push runs out).
  const placed = new Map<string, GeoPoint>();
  for (const spot of spots.sort((a, b) => byHash(a.traveller, b.traveller))) {
    const steps = Math.floor(MAX_PUSH_M[spot.traveller.anchorKind] / PUSH_STEP_M);
    let best: { point: GeoPoint; clearance: number } | null = null;
    for (let step = 0; step <= steps; step += 1) {
      const point = offset(
        spot.centre,
        spot.radius + step * PUSH_STEP_M,
        spot.angle + step * PUSH_TURN,
      );
      const clearance = Math.min(
        Infinity,
        ...[...placed.values()].map((p) => metresBetween(p, point)),
      );
      if (!best || clearance > best.clearance) best = { point, clearance };
      if (clearance >= SEPARATION_M) break;
    }
    placed.set(spot.traveller.id, best!.point);
  }
  return placed;
}
