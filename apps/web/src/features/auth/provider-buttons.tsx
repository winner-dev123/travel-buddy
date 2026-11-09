import { getLocale, getTranslations } from 'next-intl/server';
import { Mail } from 'lucide-react';
import { Button } from '@travelbuddy/ui';

function GoogleMark() {
  return (
    <svg viewBox="0 0 24 24" className="size-5" aria-hidden="true">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.1z" />
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A11 11 0 0 0 12 23z" />
      <path fill="#FBBC05" d="M5.84 14.1A6.6 6.6 0 0 1 5.5 12c0-.73.13-1.43.34-2.1V7.06H2.18A11 11 0 0 0 1 12c0 1.77.42 3.45 1.18 4.94l3.66-2.84z" />
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15A10.6 10.6 0 0 0 12 1 11 11 0 0 0 2.18 7.06l3.66 2.84C6.71 7.31 9.14 5.38 12 5.38z" />
    </svg>
  );
}

function AppleMark() {
  return (
    <svg viewBox="0 0 24 24" className="size-5" aria-hidden="true" fill="currentColor">
      <path d="M16.37 12.62c-.02-2.3 1.88-3.4 1.96-3.46-1.07-1.56-2.73-1.77-3.32-1.8-1.41-.14-2.76.83-3.48.83-.72 0-1.82-.81-3-.79-1.54.02-2.96.9-3.76 2.27-1.6 2.78-.41 6.9 1.15 9.16.76 1.1 1.67 2.34 2.86 2.3 1.15-.05 1.58-.74 2.97-.74 1.38 0 1.77.74 2.99.72 1.24-.02 2.02-1.12 2.77-2.23.87-1.28 1.23-2.52 1.25-2.58-.03-.01-2.4-.92-2.39-3.68zM14.1 5.86c.63-.77 1.06-1.83.94-2.9-.91.04-2.02.61-2.67 1.37-.58.67-1.1 1.76-.96 2.8 1.02.08 2.06-.52 2.69-1.27z" />
    </svg>
  );
}

export type ProviderOption = 'google' | 'apple' | 'email';

/**
 * Social / email entry points. Each starts an IdP flow through `/api/auth/login`; the IdP owns
 * credentials (doc 02 §8). Plain links, so they work without JavaScript. `providers` limits the
 * buttons to what the identity provider has enabled.
 */
export async function ProviderButtons({
  intent,
  next,
  providers = ['google', 'apple', 'email'],
}: {
  intent: 'login' | 'signup';
  next: string;
  providers?: readonly ProviderOption[];
}) {
  if (providers.length === 0) return null;
  const [t, locale] = await Promise.all([getTranslations('auth.providers'), getLocale()]);
  const href = (provider: string) =>
    `/api/auth/login?${new URLSearchParams({ intent, provider, next, locale }).toString()}`;
  return (
    <div className="flex flex-col gap-3">
      {providers.includes('google') ? (
        <Button asChild variant="secondary" size="lg">
          <a href={href('google')}>
            <GoogleMark />
            {t('google')}
          </a>
        </Button>
      ) : null}
      {providers.includes('apple') ? (
        <Button asChild variant="secondary" size="lg">
          <a href={href('apple')}>
            <AppleMark />
            {t('apple')}
          </a>
        </Button>
      ) : null}
      {providers.includes('email') ? (
        <Button asChild variant="secondary" size="lg">
          <a href={href('email')}>
            <Mail aria-hidden="true" />
            {t('email')}
          </a>
        </Button>
      ) : null}
    </div>
  );
}
