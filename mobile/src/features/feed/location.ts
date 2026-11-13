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
/** A remembered position is reused only when it was at least this precise (metres). */
export const GOOD_ENOUGH_M = 500;
/** A device without a fix (indoors, emulators) can wait forever: give up and say so instead. */
export const LOCATE_TIMEOUT_MS = 15_000;
/** Decimals kept before a position leaves the device: 3 is about 110 m (LOC-003). */
export const POSITION_DECIMALS = 3;
/** Worse than this, the OS gave only an approximate location (the traveller's choice). */
export const APPROXIMATE_M = 1_500;

async function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T | null> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<null>((resolve) => {
    timer = setTimeout(() => resolve(null), ms);
  });
  try {
    return await Promise.race([promise, timeout]);
  } finally {
    clearTimeout(timer);
  }
}
/** The API refuses fixes older than 15 minutes (LOC-007); the app locates again a minute before. */
export const FIX_MAX_AGE_MS = 14 * 60_000;

/**
 * The device's position for Nearby, "Near me" and Companions (LOC-001/003/006), rounded to about
 * 110 m before it leaves the device; the API uses it for one lookup and never stores it. A recent
 * position is reused only when it was precise; otherwise the device locates again (Wi-Fi, cell and
 * GPS), and a recent rough position is the last resort. When the traveller allowed only an
 * approximate location, the OS answers with a rough one and its accuracy travels with it (LOC-008).
 */
export async function getCoarsePosition(): Promise<CoarsePosition> {
  const permission = await Location.requestForegroundPermissionsAsync();
  if (permission.status !== 'granted') {
    return { status: 'denied' };
  }
  try {
    const position =
      (await Location.getLastKnownPositionAsync({
        maxAge: RECENT_MS,
        requiredAccuracy: GOOD_ENOUGH_M,
      })) ??
      (await withTimeout(
        Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced }),
        LOCATE_TIMEOUT_MS,
      )) ??
      (await Location.getLastKnownPositionAsync({ maxAge: RECENT_MS }));
    if (!position) {
      return { status: 'unavailable' };
    }
    const { latitude, longitude, accuracy } = position.coords;
    const near = `${latitude.toFixed(POSITION_DECIMALS)},${longitude.toFixed(POSITION_DECIMALS)}`;
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

/** True when the OS gave only an approximate position (the traveller chose it in the prompt). */
export function isApproximate(fix: DeviceFix | undefined): boolean {
  return typeof fix?.accuracyM === 'number' && fix.accuracyM > APPROXIMATE_M;
}
