// req: I18N-001
import { createInstance } from 'i18next';

import { DEFAULT_LOCALE, resources, SUPPORTED_LOCALES } from '../locales';
import { resolveSupportedLocale } from '../resolveLocale';

const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/;

function flattenKeys(value: unknown, prefix = ''): string[] {
  if (typeof value !== 'object' || value === null) {
    return [prefix];
  }
  return Object.entries(value).flatMap(([key, child]) =>
    flattenKeys(child, prefix ? `${prefix}.${key}` : key),
  );
}

const englishKeys = flattenKeys(resources.en.translation);
const baseKeys = (keys: string[]) => new Set(keys.map((key) => key.replace(PLURAL_SUFFIX, '')));

describe('translation resources', () => {
  it.each(SUPPORTED_LOCALES)('%s has exactly the English key set (plural-aware)', (locale) => {
    const keys = flattenKeys(resources[locale].translation);
    expect([...baseKeys(keys)].sort()).toEqual([...baseKeys(englishKeys)].sort());
  });

  it.each(SUPPORTED_LOCALES)('%s defines every CLDR plural form it needs', (locale) => {
    const keys = new Set(flattenKeys(resources[locale].translation));
    const pluralBases = new Set(
      englishKeys.filter((key) => PLURAL_SUFFIX.test(key)).map((k) => k.replace(PLURAL_SUFFIX, '')),
    );
    const categories = new Intl.PluralRules(locale).resolvedOptions().pluralCategories;
    for (const base of pluralBases) {
      for (const category of categories) {
        expect(keys).toContain(`${base}_${category}`);
      }
    }
  });

  it.each(SUPPORTED_LOCALES)('%s has no empty strings and keeps interpolation tokens', (locale) => {
    const translation = resources[locale].translation;
    const english = resources.en.translation;
    const lookup = (source: unknown, path: string): unknown =>
      path
        .split('.')
        .reduce<unknown>((node, part) => (node as Record<string, unknown>)?.[part], source);

    for (const key of flattenKeys(translation)) {
      const value = lookup(translation, key);
      expect(typeof value).toBe('string');
      expect((value as string).trim()).not.toBe('');

      const englishKey = englishKeys.find(
        (k) => k.replace(PLURAL_SUFFIX, '') === key.replace(PLURAL_SUFFIX, ''),
      );
      const englishValue = englishKey ? (lookup(english, englishKey) as string) : '';
      const tokens = (text: string) => (text.match(/\{\{\s*\w+\s*\}\}/g) ?? []).sort();
      expect(tokens(value as string)).toEqual(tokens(englishValue));
    }
  });

  it('applies French and German plural forms through i18next', async () => {
    const instance = createInstance();
    await instance.init({ resources, lng: 'fr', fallbackLng: DEFAULT_LOCALE, initAsync: false });
    expect(instance.t('placeholder.plannedCapabilities', { count: 1 })).toBe(
      '1 fonctionnalité prévue',
    );
    expect(instance.t('placeholder.plannedCapabilities', { count: 3 })).toBe(
      '3 fonctionnalités prévues',
    );
    await instance.changeLanguage('de');
    expect(instance.t('placeholder.plannedCapabilities', { count: 1 })).toBe('1 geplante Funktion');
    expect(instance.t('placeholder.plannedCapabilities', { count: 2 })).toBe(
      '2 geplante Funktionen',
    );
  });
});

describe('resolveSupportedLocale', () => {
  it.each([
    [['pt-BR'], 'pt-BR'],
    [['pt-PT'], 'pt-BR'],
    [['pt_BR'], 'pt-BR'],
    [['es-MX'], 'es'],
    [['de-AT', 'en-US'], 'de'],
    [['ja-JP', 'fr-CA'], 'fr'],
    [['ja-JP'], 'en'],
    [[], 'en'],
    [[''], 'en'],
  ])('%j → %s', (tags, expected) => {
    expect(resolveSupportedLocale(tags)).toBe(expected);
  });
});
