import type { LocaleCode, Messages } from '@travelbuddy/i18n';

declare module 'next-intl' {
  interface AppConfig {
    Locale: LocaleCode;
    Messages: Messages;
  }
}
