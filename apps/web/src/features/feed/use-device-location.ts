'use client';

import { useCallback, useState } from 'react';
import { toNearParam } from '@travelbuddy/validation';

export type LocationStatus = 'idle' | 'locating' | 'ready' | 'denied' | 'unavailable';

/**
 * Request-scoped device location for the feed (doc 02 §6). The position is rounded to ~110 m
 * before it leaves this hook, lives only in component memory, and is never persisted or logged.
 */
export function useDeviceLocation() {
  const [near, setNear] = useState<string | null>(null);
  const [status, setStatus] = useState<LocationStatus>('idle');

  const locate = useCallback(() => {
    if (typeof navigator === 'undefined' || !('geolocation' in navigator)) {
      setStatus('unavailable');
      return;
    }
    setStatus('locating');
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        const value = toNearParam(pos.coords.latitude, pos.coords.longitude);
        setNear(value);
        setStatus(value ? 'ready' : 'unavailable');
      },
      (err) => setStatus(err.code === err.PERMISSION_DENIED ? 'denied' : 'unavailable'),
      { enableHighAccuracy: false, maximumAge: 5 * 60_000, timeout: 10_000 },
    );
  }, []);

  /** Locates silently only if the permission was already granted (no surprise prompts). */
  const locateIfGranted = useCallback(async () => {
    try {
      const permission = await navigator.permissions?.query({ name: 'geolocation' as PermissionName });
      if (permission?.state === 'granted') locate();
    } catch {
      // Permissions API unsupported: wait for an explicit user action.
    }
  }, [locate]);

  const clear = useCallback(() => {
    setNear(null);
    setStatus('idle');
  }, []);

  return { near, status, locate, locateIfGranted, clear };
}
