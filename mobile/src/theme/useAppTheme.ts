import { useMemo } from 'react';
import { useColorScheme } from 'react-native';

import { useSettingsStore } from '@/state/settingsStore';

import { buildTheme, type ColorSchemeName, type Theme } from './tokens';

export function resolveColorScheme(
  preference: 'system' | ColorSchemeName,
  systemScheme: string | null | undefined,
): ColorSchemeName {
  if (preference !== 'system') {
    return preference;
  }
  return systemScheme === 'dark' ? 'dark' : 'light';
}

/** Current theme: the user's explicit preference, otherwise the OS setting. */
export function useAppTheme(): Theme {
  const systemScheme = useColorScheme();
  const preference = useSettingsStore((state) => state.themePreference);
  const scheme = resolveColorScheme(preference, systemScheme);
  return useMemo(() => buildTheme(scheme), [scheme]);
}
