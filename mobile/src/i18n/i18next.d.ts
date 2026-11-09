import 'i18next';

import type { TranslationResource } from './locales';

// Compile-time checking of translation keys against en.json.
declare module 'i18next' {
  interface CustomTypeOptions {
    defaultNS: 'translation';
    resources: {
      translation: TranslationResource;
    };
    returnNull: false;
  }
}
