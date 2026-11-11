import { create } from 'zustand';

import type { SupportedLocale } from '@/i18n/locales';
import type { ColorSchemeName } from '@/theme/tokens';

export type ThemePreference = 'system' | ColorSchemeName;

export interface SettingsState {
  /** `null` = follow the device language. */
  localeOverride: SupportedLocale | null;
  themePreference: ThemePreference;
  setLocaleOverride: (locale: SupportedLocale | null) => void;
  setThemePreference: (preference: ThemePreference) => void;
}

/**
 * Client-only UI preferences. The appearance defaults to dark (the look the app is designed
 * around) and is remembered on the device by `uiPreferences.ts`; the language is saved to the
 * account instead (I18N-002).
 */
export const useSettingsStore = create<SettingsState>()((set) => ({
  localeOverride: null,
  themePreference: 'dark',
  setLocaleOverride: (localeOverride) => set({ localeOverride }),
  setThemePreference: (themePreference) => set({ themePreference }),
}));
