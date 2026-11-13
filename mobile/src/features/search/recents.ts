import { File, Paths } from 'expo-file-system';
import { create } from 'zustand';

import { suggestionKey, type Suggestion } from './api';

/**
 * The last towns and places chosen in search, newest first, kept on this device only (a small
 * file in the app's documents) so the search sheet can offer them like a ride app does. Nothing
 * is sent anywhere; signing out forgets them.
 */
export const MAX_RECENTS = 6;

const recentsFile = () => new File(Paths.document, 'search-recents.json');

function isSuggestion(value: unknown): value is Suggestion {
  if (!value || typeof value !== 'object') return false;
  const item = value as Partial<Suggestion>;
  const destination = item.destination as { id?: unknown; name?: unknown } | undefined;
  if (typeof destination?.id !== 'string' || typeof destination.name !== 'string') return false;
  if (item.type === 'destination') return true;
  const place = (item as { place?: { id?: unknown; name?: unknown } }).place;
  return item.type === 'place' && typeof place?.id === 'string' && typeof place.name === 'string';
}

function readRecents(): Suggestion[] {
  try {
    const file = recentsFile();
    if (!file.exists) return [];
    const saved: unknown = JSON.parse(file.textSync());
    return Array.isArray(saved) ? saved.filter(isSuggestion).slice(0, MAX_RECENTS) : [];
  } catch {
    return [];
  }
}

function writeRecents(items: Suggestion[]): void {
  try {
    if (items.length === 0) {
      const file = recentsFile();
      if (file.exists) file.delete();
      return;
    }
    recentsFile().writeSync(JSON.stringify(items));
  } catch {
    // Recents are a convenience: without storage they last until the app closes.
  }
}

interface RecentsState {
  items: Suggestion[] | null; // null until read from the device
  load: () => Suggestion[];
  remember: (suggestion: Suggestion) => void;
  forget: () => void;
}

export const useRecentSearches = create<RecentsState>((set, get) => ({
  items: null,
  load: () => {
    const current = get().items;
    if (current) return current;
    const items = readRecents();
    set({ items });
    return items;
  },
  remember: (suggestion) => {
    const key = suggestionKey(suggestion);
    const items = [
      suggestion,
      ...get()
        .load()
        .filter((item) => suggestionKey(item) !== key),
    ].slice(0, MAX_RECENTS);
    set({ items });
    writeRecents(items);
  },
  forget: () => {
    set({ items: [] });
    writeRecents([]);
  },
}));

/** Signing out forgets this device's searches. */
export function forgetRecentSearches(): void {
  useRecentSearches.getState().forget();
}
