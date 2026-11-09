import { hasLocale } from 'next-intl';
import { getRequestConfig } from 'next-intl/server';
import { loadMessages } from '@travelbuddy/i18n';
import { routing } from './routing';

export default getRequestConfig(async ({ requestLocale }) => {
  const requested = await requestLocale;
  const locale = hasLocale(routing.locales, requested) ? requested : routing.defaultLocale;
  return {
    locale,
    messages: await loadMessages(locale),
    // Server default. Trip and event dates pass the destination's IANA zone explicitly.
    timeZone: 'UTC',
  };
});
