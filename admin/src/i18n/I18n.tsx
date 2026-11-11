import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';

import { KEYS, readItem, writeItem } from '../auth/storage';
import { en, type MessageKey } from './en';
import { pt } from './pt';

export type Locale = 'en' | 'pt-BR';
export const LOCALES: { id: Locale; label: string }[] = [
  { id: 'en', label: 'English' },
  { id: 'pt-BR', label: 'Português' },
];

const CATALOGS: Record<Locale, Record<MessageKey, string>> = { en, 'pt-BR': pt };

export type Translate = (key: MessageKey, values?: Record<string, string | number>) => string;

interface I18n {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: Translate;
  /** "3 Nov 2026, 14:05" in the console language. */
  dateTime: (value: string | Date) => string;
  date: (value: string | Date) => string;
  /** "2 h", "3 d" style durations. */
  age: (seconds: number) => string;
  /** Minor units to "R$ 19,90" / "$4.99". */
  money: (amountMinor: number, currency: string) => string;
  number: (value: number) => string;
}

const I18nContext = createContext<I18n | null>(null);

function initialLocale(): Locale {
  const saved = readItem('local', KEYS.locale);
  if (saved === 'en' || saved === 'pt-BR') return saved;
  return typeof navigator !== 'undefined' && navigator.language?.toLowerCase().startsWith('pt')
    ? 'pt-BR'
    : 'en';
}

const ZERO_DECIMAL = new Set(['JPY', 'KRW', 'VND', 'CLP', 'ISK', 'UGX', 'XAF', 'XOF', 'PYG']);

export function I18nProvider({ children, locale: fixed }: { children: ReactNode; locale?: Locale }) {
  const [locale, setLocaleState] = useState<Locale>(() => fixed ?? initialLocale());

  const setLocale = useCallback((next: Locale) => {
    writeItem('local', KEYS.locale, next);
    setLocaleState(next);
    document.documentElement.lang = next;
  }, []);

  const value = useMemo<I18n>(() => {
    const catalog = CATALOGS[locale];
    const t: Translate = (key, values) => {
      let text = catalog[key] ?? en[key] ?? key;
      for (const [name, replacement] of Object.entries(values ?? {})) {
        text = text.replaceAll(`{${name}}`, String(replacement));
      }
      return text;
    };
    const dateTimeFormat = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' });
    const dateFormat = new Intl.DateTimeFormat(locale, { dateStyle: 'medium' });
    const numberFormat = new Intl.NumberFormat(locale);
    return {
      locale,
      setLocale,
      t,
      dateTime: (v) => dateTimeFormat.format(typeof v === 'string' ? new Date(v) : v),
      date: (v) => dateFormat.format(typeof v === 'string' ? new Date(v) : v),
      age: (seconds) => {
        const units: [number, Intl.RelativeTimeFormatUnit][] = [
          [86400, 'day'],
          [3600, 'hour'],
          [60, 'minute'],
        ];
        for (const [size, unit] of units) {
          if (seconds >= size) {
            return new Intl.NumberFormat(locale, {
              style: 'unit',
              unit,
              unitDisplay: 'short',
            }).format(Math.floor(seconds / size));
          }
        }
        return new Intl.NumberFormat(locale, { style: 'unit', unit: 'second', unitDisplay: 'short' }).format(
          Math.max(0, Math.floor(seconds)),
        );
      },
      money: (amountMinor, currency) => {
        const code = currency.toUpperCase();
        const major = ZERO_DECIMAL.has(code) ? amountMinor : amountMinor / 100;
        try {
          return new Intl.NumberFormat(locale, { style: 'currency', currency: code }).format(major);
        } catch {
          return `${major} ${code}`;
        }
      },
      number: (v) => numberFormat.format(v),
    };
  }, [locale, setLocale]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18n {
  const value = useContext(I18nContext);
  if (!value) throw new Error('useI18n outside I18nProvider');
  return value;
}
