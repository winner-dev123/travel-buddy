import * as Location from 'expo-location';

/** A device position as the API receives it: rounded, with when and how precisely it was taken. */
export interface DeviceFix {
  near: string;
  capturedAt: string;
  accuracyM: number | null;
}

export type CoarsePosition =
  | { status: 'granted'; near: string; fix: DeviceFix }
  | { status: 'denied' }
  | { status: 'unavailable' };

const RECENT_MS = 10 * 60_000;
/** The API refuses fixes older than 15 minutes (LOC-007); the app locates again a minute before. */
export const FIX_MAX_AGE_MS = 14 * 60_000;

/**
 * The device's approximate position for the Nearby feed (LOC-001/006). Rounded to two decimals
 * (about 1 km) before it leaves the device: the API only needs the city and never stores it.
 */
export async function getCoarsePosition(): Promise<CoarsePosition> {
  const permission = await Location.requestForegroundPermissionsAsync();
  if (permission.status !== 'granted') {
    return { status: 'denied' };
  }
  try {
    const position =
      (await Location.getLastKnownPositionAsync({ maxAge: RECENT_MS })) ??
      (await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Low }));
    if (!position) {
      return { status: 'unavailable' };
    }
    const { latitude, longitude, accuracy } = position.coords;
    const near = `${latitude.toFixed(2)},${longitude.toFixed(2)}`;
    const taken = typeof position.timestamp === 'number' ? position.timestamp : Date.now();
    return {
      status: 'granted',
      near,
      fix: {
        near,
        capturedAt: new Date(taken).toISOString(),
        accuracyM: typeof accuracy === 'number' ? accuracy : null,
      },
    };
  } catch {
    return { status: 'unavailable' };
  }
}

export function isFresh(fix: DeviceFix, now: number = Date.now()): boolean {
  return now - Date.parse(fix.capturedAt) < FIX_MAX_AGE_MS;
}

/** The fix if still fresh, else a new one (undefined when location is no longer available). */
export async function freshFix(fix: DeviceFix | undefined): Promise<DeviceFix | undefined> {
  if (!fix || isFresh(fix)) return fix;
  const again = await getCoarsePosition();
  return again.status === 'granted' ? again.fix : undefined;
}

/** `near_ts` and `near_accuracy_m` for the API (LOC-007, LOC-008). */
export function fixParams(fix: DeviceFix | undefined): Record<string, string | number> {
  if (!fix) return {};
  return {
    near_ts: fix.capturedAt,
    ...(fix.accuracyM !== null ? { near_accuracy_m: Math.round(fix.accuracyM) } : {}),
  };
}
