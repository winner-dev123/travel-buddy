import { defineRouting } from 'next-intl/routing';
import { DEFAULT_LOCALE, LOCALES, SUPPORTED_LOCALES } from '@travelbuddy/i18n';

const prefixes = Object.fromEntries(LOCALES.filter((l) => l.prefix).map((l) => [l.code, l.prefix]));

export const routing = defineRouting({
  locales: SUPPORTED_LOCALES,
  defaultLocale: DEFAULT_LOCALE,
  localePrefix: { mode: 'as-needed', prefixes },
  // URL → NEXT_LOCALE cookie → Accept-Language. IP address is never used (docs/web/01 §12).
  localeDetection: true,
  // We emit hreflang alternates in page metadata ourselves (canonical per page).
  alternateLinks: false,
});
