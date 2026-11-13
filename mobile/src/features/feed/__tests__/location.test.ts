// req: LOC-003, LOC-007, LOC-008
import * as Location from 'expo-location';

import {
  fixParams,
  getCoarsePosition,
  GOOD_ENOUGH_M,
  isApproximate,
  isFresh,
  LOCATE_TIMEOUT_MS,
} from '../location';

jest.mock('expo-location', () => ({
  requestForegroundPermissionsAsync: jest.fn(async () => ({ status: 'granted' })),
  getLastKnownPositionAsync: jest.fn(async () => null),
  getCurrentPositionAsync: jest.fn(),
  Accuracy: { Low: 2, Balanced: 3 },
}));

const current = Location.getCurrentPositionAsync as jest.Mock;
const lastKnown = Location.getLastKnownPositionAsync as jest.Mock;

afterEach(() => {
  jest.useRealTimers();
  jest.clearAllMocks();
});

it('rounds the position to about 110 m and keeps when and how precisely it was taken', async () => {
  current.mockResolvedValue({
    coords: { latitude: 38.72231, longitude: -9.13934, accuracy: 1250.4 },
    timestamp: Date.parse('2026-11-10T12:00:00Z'),
  });
  const position = await getCoarsePosition();
  expect(position).toEqual({
    status: 'granted',
    near: '38.722,-9.139',
    fix: { near: '38.722,-9.139', capturedAt: '2026-11-10T12:00:00.000Z', accuracyM: 1250.4 },
  });
  if (position.status !== 'granted') throw new Error('expected a fix');
  expect(fixParams(position.fix)).toEqual({
    near_ts: '2026-11-10T12:00:00.000Z',
    near_accuracy_m: 1250,
  });
  expect(isFresh(position.fix, Date.parse('2026-11-10T12:13:00Z'))).toBe(true);
  expect(isFresh(position.fix, Date.parse('2026-11-10T12:15:00Z'))).toBe(false);
  expect(current).toHaveBeenCalledWith({ accuracy: Location.Accuracy.Balanced });
});

it('reuses a recent position only when it was precise', async () => {
  lastKnown.mockResolvedValueOnce({
    coords: { latitude: -23.55052, longitude: -46.633309, accuracy: 35 },
    timestamp: Date.parse('2026-11-10T12:00:00Z'),
  });
  const position = await getCoarsePosition();
  expect(position).toMatchObject({ status: 'granted', near: '-23.551,-46.633' });
  expect(lastKnown).toHaveBeenCalledWith(
    expect.objectContaining({ requiredAccuracy: GOOD_ENOUGH_M }),
  );
  expect(current).not.toHaveBeenCalled();
});

it('falls back to a recent rough position when the device cannot locate again', async () => {
  jest.useFakeTimers();
  current.mockReturnValue(new Promise(() => undefined)); // never resolves
  lastKnown
    .mockResolvedValueOnce(null) // nothing precise
    .mockResolvedValueOnce({
      coords: { latitude: -22.9068, longitude: -43.1729, accuracy: 2400 },
      timestamp: Date.parse('2026-11-10T12:00:00Z'),
    });
  const pending = getCoarsePosition();
  await jest.advanceTimersByTimeAsync(LOCATE_TIMEOUT_MS);
  const position = await pending;
  expect(position).toMatchObject({ status: 'granted', near: '-22.907,-43.173' });
  if (position.status !== 'granted') throw new Error('expected a fix');
  expect(isApproximate(position.fix)).toBe(true);
});

it('tells an approximate position from a precise one', () => {
  const fix = { near: '1.000,2.000', capturedAt: '2026-11-10T12:00:00.000Z' };
  expect(isApproximate({ ...fix, accuracyM: 40 })).toBe(false);
  expect(isApproximate({ ...fix, accuracyM: 3000 })).toBe(true);
  expect(isApproximate({ ...fix, accuracyM: null })).toBe(false);
  expect(isApproximate(undefined)).toBe(false);
});

it('gives up when the device never gets a fix', async () => {
  jest.useFakeTimers();
  current.mockReturnValue(new Promise(() => undefined)); // never resolves
  const pending = getCoarsePosition();
  await jest.advanceTimersByTimeAsync(LOCATE_TIMEOUT_MS);
  await expect(pending).resolves.toEqual({ status: 'unavailable' });
});
