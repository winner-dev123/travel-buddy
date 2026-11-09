import { DEFAULT_LOCALE, isLocale, localeInfo, type LocaleCode } from '@travelbuddy/i18n';

/** Prefixes a root-relative path with the locale's URL prefix (none for the default locale). */
export function localizedPath(locale: string | null | undefined, path: string): string {
  const code: LocaleCode = isLocale(locale) ? locale : DEFAULT_LOCALE;
  const prefix = localeInfo(code).prefix;
  if (!prefix) return path;
  return path === '/' ? prefix : `${prefix}${path}`;
}

export function absoluteUrl(siteUrl: string, locale: string, path: string): string {
  return `${siteUrl}${localizedPath(locale, path)}`;
}

export const destinationHref = (path: string) => `/destinations/${path}`;
export const storyHref = (id: string) => `/stories/${id}`;
