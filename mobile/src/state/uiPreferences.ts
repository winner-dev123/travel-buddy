import { File, Paths } from 'expo-file-system';

import { type ThemePreference, useSettingsStore } from './settingsStore';

/**
 * The appearance choice, kept in a small file in the app's documents so it survives a restart.
 * It is read synchronously before the first frame (no flash of the wrong theme). Nothing here
 * is sensitive, and a device that can't read or write the file simply keeps the default.
 */
const THEME_PREFERENCES: readonly ThemePreference[] = ['dark', 'light', 'system'];

const preferencesFile = () => new File(Paths.document, 'ui-preferences.json');

export function readSavedThemePreference(): ThemePreference | null {
  try {
    const file = preferencesFile();
    if (!file.exists) {
      return null;
    }
    const saved = (JSON.parse(file.textSync()) as { theme?: unknown }).theme;
    return THEME_PREFERENCES.includes(saved as ThemePreference) ? (saved as ThemePreference) : null;
  } catch {
    return null;
  }
}

/** Apply the saved appearance to the settings store. Call once, before the first render. */
export function hydrateUiPreferences(): void {
  const saved = readSavedThemePreference();
  if (saved) {
    useSettingsStore.getState().setThemePreference(saved);
  }
}

/** Change the appearance now and remember it for the next launch. */
export function chooseThemePreference(preference: ThemePreference): void {
  useSettingsStore.getState().setThemePreference(preference);
  try {
    preferencesFile().writeSync(JSON.stringify({ theme: preference }));
  } catch {
    // The choice still applies until the app closes.
  }
}
