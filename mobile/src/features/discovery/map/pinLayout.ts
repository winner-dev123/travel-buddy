import type { GeoPoint } from './mapPage';

/**
 * Where to draw each traveller (DISC-004, DISC-012, ADR-0005, ADR-0030).
 *
 * The API never says where anyone is, only the city or neighbourhood they share. Each pin is
 * placed around that area's public centre, on a spiral ordered by a hash of the traveller's id,
 * so pins don't overlap. The spot therefore carries no information beyond the area label, and the
 * map says so.
 */

/** How far from an area's centre pins are spread, in metres. */
export const SPREAD_M = {
  city: { min: 800, max: 2200 },
  neighborhood: { min: 120, max: 420 },
} as const;

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
  const placed = new Map<string, GeoPoint>();
  for (const [anchorId, group] of groups) {
    const centre = centres.get(anchorId);
    if (!centre) continue;
    const ordered = [...group].sort(
      (a, b) => stableHash(a.id) - stableHash(b.id) || a.id.localeCompare(b.id),
    );
    const start = (stableHash(anchorId) / 0xffffffff) * 2 * Math.PI;
    ordered.forEach((traveller, index) => {
      const spread = SPREAD_M[traveller.anchorKind];
      const share = Math.sqrt((index + 0.5) / ordered.length);
      const radius = spread.min + (spread.max - spread.min) * share;
      const angle = start + index * GOLDEN_ANGLE;
      const lat = centre.lat + (radius * Math.cos(angle)) / METRES_PER_DEGREE;
      const lng =
        centre.lng +
        (radius * Math.sin(angle)) /
          (METRES_PER_DEGREE * Math.max(0.05, Math.cos((centre.lat * Math.PI) / 180)));
      placed.set(traveller.id, { lat, lng });
    });
  }
  return placed;
}
