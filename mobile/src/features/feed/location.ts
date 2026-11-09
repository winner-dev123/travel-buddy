import * as Location from 'expo-location';

export type CoarsePosition =
  { status: 'granted'; near: string } | { status: 'denied' } | { status: 'unavailable' };

const RECENT_MS = 10 * 60_000;

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
    const { latitude, longitude } = position.coords;
    return { status: 'granted', near: `${latitude.toFixed(2)},${longitude.toFixed(2)}` };
  } catch {
    return { status: 'unavailable' };
  }
}
