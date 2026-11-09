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
 * Client-only UI preferences. Not persisted yet: persistence (expo-sqlite
 * kv-store) and server sync of `user_preferences` arrive with Phase 1 profiles.
 */
export const useSettingsStore = create<SettingsState>()((set) => ({
  localeOverride: null,
  themePreference: 'system',
  setLocaleOverride: (localeOverride) => set({ localeOverride }),
  setThemePreference: (themePreference) => set({ themePreference }),
}));
