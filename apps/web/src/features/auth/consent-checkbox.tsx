'use client';

import type { UseFormRegisterReturn } from 'react-hook-form';
import { useTranslations } from 'next-intl';
import { Link } from '@/i18n/navigation';

/** Terms + privacy consent checkbox shared by the registration forms. */
export function ConsentCheckbox({ registration, error }: { registration: UseFormRegisterReturn; error?: string }) {
  const t = useTranslations('auth.register');
  return (
    <div className="flex flex-col gap-1.5">
      <label className="flex items-start gap-3 text-sm">
        <input type="checkbox" className="mt-0.5 size-4 accent-[var(--tb-primary)]" aria-invalid={error ? true : undefined} {...registration} />
        <span>
          {t.rich('terms', {
            terms: (chunks) => (
              <Link href="/legal/terms" className="text-primary underline">
                {chunks}
              </Link>
            ),
            privacy: (chunks) => (
              <Link href="/legal/privacy" className="text-primary underline">
                {chunks}
              </Link>
            ),
          })}
        </span>
      </label>
      {error ? (
        <p role="alert" className="text-xs font-medium text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
