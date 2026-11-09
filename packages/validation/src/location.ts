/**
 * Location privacy helpers (doc 02 §6).
 *
 * Device coordinates are request-scoped only. Clients round them before they leave the device,
 * and the server rounds again and discards them after resolving a destination. Nothing here
 * stores or logs coordinates.
 */

/** 3 decimal places ≈ 110 m at the equator, the precision the platform accepts. */
export const NEAR_PRECISION_DECIMALS = 3;

export function roundCoordinate(value: number, decimals = NEAR_PRECISION_DECIMALS): number {
  const factor = 10 ** decimals;
  // `+ 0` normalizes -0 to 0 so that the serialized value is stable.
  return Math.round(value * factor) / factor + 0;
}

export function isValidLatitude(lat: number): boolean {
  return Number.isFinite(lat) && lat >= -90 && lat <= 90;
}

export function isValidLongitude(lng: number): boolean {
  return Number.isFinite(lng) && lng >= -180 && lng <= 180;
}

/** Builds the `near` query value: `lat,lng`, rounded. Returns null for invalid input. */
export function toNearParam(lat: number, lng: number): string | null {
  if (!isValidLatitude(lat) || !isValidLongitude(lng)) return null;
  return `${roundCoordinate(lat)},${roundCoordinate(lng)}`;
}

/** Parses and re-rounds a `near` value. Returns null when malformed. */
export function parseNearParam(near: string | null | undefined): { lat: number; lng: number } | null {
  if (!near) return null;
  const match = /^(-?\d{1,2}(?:\.\d+)?),(-?\d{1,3}(?:\.\d+)?)$/.exec(near.trim());
  if (!match) return null;
  const lat = Number(match[1]);
  const lng = Number(match[2]);
  if (!isValidLatitude(lat) || !isValidLongitude(lng)) return null;
  return { lat: roundCoordinate(lat), lng: roundCoordinate(lng) };
}

/** Great-circle distance in kilometres (haversine). For public places only. */
export function distanceKm(
  a: { lat: number; lng: number },
  b: { lat: number; lng: number },
): number {
  const R = 6371;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}
