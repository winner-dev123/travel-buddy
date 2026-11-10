// req: LOC-007, LOC-008
import * as Location from 'expo-location';

import { fixParams, getCoarsePosition, isFresh, LOCATE_TIMEOUT_MS } from '../location';

jest.mock('expo-location', () => ({
  requestForegroundPermissionsAsync: jest.fn(async () => ({ status: 'granted' })),
  getLastKnownPositionAsync: jest.fn(async () => null),
  getCurrentPositionAsync: jest.fn(),
  Accuracy: { Low: 2 },
}));

const current = Location.getCurrentPositionAsync as jest.Mock;

afterEach(() => {
  jest.useRealTimers();
  jest.clearAllMocks();
});

it('rounds the position and keeps when and how precisely it was taken', async () => {
  current.mockResolvedValue({
    coords: { latitude: 38.72231, longitude: -9.13934, accuracy: 1250.4 },
    timestamp: Date.parse('2026-11-10T12:00:00Z'),
  });
  const position = await getCoarsePosition();
  expect(position).toEqual({
    status: 'granted',
    near: '38.72,-9.14',
    fix: { near: '38.72,-9.14', capturedAt: '2026-11-10T12:00:00.000Z', accuracyM: 1250.4 },
  });
  if (position.status !== 'granted') throw new Error('expected a fix');
  expect(fixParams(position.fix)).toEqual({
    near_ts: '2026-11-10T12:00:00.000Z',
    near_accuracy_m: 1250,
  });
  expect(isFresh(position.fix, Date.parse('2026-11-10T12:13:00Z'))).toBe(true);
  expect(isFresh(position.fix, Date.parse('2026-11-10T12:15:00Z'))).toBe(false);
});

it('gives up when the device never gets a fix', async () => {
  jest.useFakeTimers();
  current.mockReturnValue(new Promise(() => undefined)); // never resolves
  const pending = getCoarsePosition();
  await jest.advanceTimersByTimeAsync(LOCATE_TIMEOUT_MS);
  await expect(pending).resolves.toEqual({ status: 'unavailable' });
});
