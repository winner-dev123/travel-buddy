import { useSyncExternalStore } from 'react';

/**
 * Per-browser preference: may the feed use this device's location? Location itself is never
 * stored — when enabled, the feed asks the browser for a fresh position per request, rounds it to
 * ~110 m and sends it as a request-scoped `near` parameter (doc 02 §6).
 */
const KEY = 'tb-feed-location';
const EVENT = 'tb-feed-location-change';

export function getFeedLocationPreference(): boolean {
  try {
    return localStorage.getItem(KEY) === 'on';
  } catch {
    return false;
  }
}

export function setFeedLocationPreference(on: boolean): void {
  try {
    if (on) localStorage.setItem(KEY, 'on');
    else localStorage.removeItem(KEY);
  } catch {
    // Storage unavailable: the feed simply won't use location.
  }
  window.dispatchEvent(new Event(EVENT));
}

function subscribe(callback: () => void): () => void {
  window.addEventListener('storage', callback);
  window.addEventListener(EVENT, callback);
  return () => {
    window.removeEventListener('storage', callback);
    window.removeEventListener(EVENT, callback);
  };
}

/** Reactive view of the preference; `false` during server rendering. */
export function useFeedLocationPreference(): boolean {
  return useSyncExternalStore(subscribe, getFeedLocationPreference, () => false);
}
