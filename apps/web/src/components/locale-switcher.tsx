'use client';

import { useTransition } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { Globe } from 'lucide-react';
import { LOCALES, type LocaleCode } from '@travelbuddy/i18n';
import { cn } from '@travelbuddy/ui';
import { usePathname, useRouter } from '@/i18n/navigation';

/** Language picker. Switching keeps the current page; next-intl persists the choice in NEXT_LOCALE. */
export function LocaleSwitcher({ className }: { className?: string }) {
  const t = useTranslations('locale');
  const locale = useLocale();
  const router = useRouter();
  const pathname = usePathname();
  const [pending, startTransition] = useTransition();

  return (
    <label className={cn('relative inline-flex items-center gap-1.5 text-sm text-muted-foreground', className)}>
      <Globe className="size-4" aria-hidden="true" />
      <span className="sr-only">{t('label')}</span>
      <select
        value={locale}
        disabled={pending}
        onChange={(event) => {
          const next = event.target.value as LocaleCode;
          // Read at interaction time: avoids useSearchParams, which would force a Suspense boundary
          // (or client-side bailout) on every statically generated page that renders the switcher.
          const query = window.location.search.slice(1);
          startTransition(() => {
            router.replace(query ? `${pathname}?${query}` : pathname, { locale: next });
          });
        }}
        className="cursor-pointer appearance-none rounded-md bg-transparent py-1 pe-1 font-medium text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {LOCALES.map((l) => (
          <option key={l.code} value={l.code} lang={l.bcp47}>
            {l.label}
          </option>
        ))}
      </select>
    </label>
  );
}
