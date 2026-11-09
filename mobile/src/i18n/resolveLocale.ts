import { DEFAULT_LOCALE, SUPPORTED_LOCALES, type SupportedLocale } from './locales';

/**
 * Picks the best supported locale for an ordered list of BCP 47 tags
 * (most preferred first), e.g. from `expo-localization`'s `getLocales()`.
 *
 * Matching per tag: exact (case-insensitive) → same language with any region
 * (`pt-PT` → `pt-BR`, `es-MX` → `es`). Falls back to English.
 */
export function resolveSupportedLocale(preferredTags: readonly string[]): SupportedLocale {
  for (const tag of preferredTags) {
    const normalized = tag.trim().replace('_', '-').toLowerCase();
    if (!normalized) {
      continue;
    }
    const exact = SUPPORTED_LOCALES.find((locale) => locale.toLowerCase() === normalized);
    if (exact) {
      return exact;
    }
    const language = normalized.split('-')[0];
    const sameLanguage = SUPPORTED_LOCALES.find(
      (locale) => locale.toLowerCase().split('-')[0] === language,
    );
    if (sameLanguage) {
      return sameLanguage;
    }
  }
  return DEFAULT_LOCALE;
}
