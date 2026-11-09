import { getLocales } from 'expo-localization';
import { createInstance } from 'i18next';
import { initReactI18next } from 'react-i18next';

import { DEFAULT_LOCALE, resources, type SupportedLocale } from './locales';
import { resolveSupportedLocale } from './resolveLocale';

export function detectDeviceLocale(): SupportedLocale {
  const tags = getLocales().map((locale) => locale.languageTag);
  return resolveSupportedLocale(tags);
}

/** App-wide i18next instance, registered with react-i18next on first import. */
export const i18n = createInstance();

void i18n.use(initReactI18next).init({
  resources,
  lng: detectDeviceLocale(),
  fallbackLng: DEFAULT_LOCALE,
  supportedLngs: Object.keys(resources),
  // Resources are bundled, so initialise synchronously (no flash of raw keys).
  initAsync: false,
  interpolation: {
    // React already escapes rendered strings.
    escapeValue: false,
  },
  returnNull: false,
});

export { SUPPORTED_LOCALES, type SupportedLocale } from './locales';
