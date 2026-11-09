import de from './de.json';
import en from './en.json';
import es from './es.json';
import fr from './fr.json';
import ptBR from './pt-BR.json';

/**
 * Supported UI locales (BCP 47). Adding a language = add a JSON file with the
 * same key set as `en.json` (enforced by the parity test) and register it here.
 */
export const SUPPORTED_LOCALES = ['en', 'es', 'pt-BR', 'fr', 'de'] as const;
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

export const DEFAULT_LOCALE: SupportedLocale = 'en';

export type TranslationResource = typeof en;

export const resources: Record<SupportedLocale, { translation: TranslationResource }> = {
  en: { translation: en },
  es: { translation: es },
  'pt-BR': { translation: ptBR },
  fr: { translation: fr },
  de: { translation: de },
};

/** Locales written right-to-left. None of the launch locales are RTL. */
export const RTL_LOCALES: readonly string[] = [];
