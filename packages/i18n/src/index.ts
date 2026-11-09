import { SUPPORTED_LOCALES, type LocaleCode } from '@travelbuddy/domain-types';
import type en from '../messages/en.json';

export { SUPPORTED_LOCALES, type LocaleCode };

export type TextDirection = 'ltr' | 'rtl';

export interface LocaleInfo {
  code: LocaleCode;
  /** Endonym shown in the language switcher. */
  label: string;
  /** URL prefix. The default locale has none. */
  prefix: string;
  /** BCP 47 tag used for `hreflang`, `<html lang>` and Intl formatting. */
  bcp47: string;
  dir: TextDirection;
  /** Default distance units for new users of this locale (user preference wins). */
  units: 'metric' | 'imperial';
}

export const DEFAULT_LOCALE: LocaleCode = 'en';

/**
 * The single list of locales. Adding a locale means adding an entry here and a message file;
 * layouts already support `dir: 'rtl'` through logical CSS properties.
 */
export const LOCALES: readonly LocaleInfo[] = [
  { code: 'en', label: 'English', prefix: '', bcp47: 'en', dir: 'ltr', units: 'metric' },
  { code: 'es', label: 'Español', prefix: '/es', bcp47: 'es', dir: 'ltr', units: 'metric' },
  { code: 'pt-BR', label: 'Português (Brasil)', prefix: '/pt-br', bcp47: 'pt-BR', dir: 'ltr', units: 'metric' },
  { code: 'fr', label: 'Français', prefix: '/fr', bcp47: 'fr', dir: 'ltr', units: 'metric' },
  { code: 'de', label: 'Deutsch', prefix: '/de', bcp47: 'de', dir: 'ltr', units: 'metric' },
];

export function isLocale(value: unknown): value is LocaleCode {
  return typeof value === 'string' && (SUPPORTED_LOCALES as readonly string[]).includes(value);
}

export function localeInfo(code: LocaleCode): LocaleInfo {
  return LOCALES.find((l) => l.code === code) ?? (LOCALES[0] as LocaleInfo);
}

/** Message catalog shape, derived from the English source catalog. */
export type Messages = typeof en;

export async function loadMessages(locale: LocaleCode): Promise<Messages> {
  switch (locale) {
    case 'es':
      return (await import('../messages/es.json')).default;
    case 'pt-BR':
      return (await import('../messages/pt-BR.json')).default;
    case 'fr':
      return (await import('../messages/fr.json')).default;
    case 'de':
      return (await import('../messages/de.json')).default;
    default:
      return (await import('../messages/en.json')).default;
  }
}
