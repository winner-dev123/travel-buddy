'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useLocale, useTranslations } from 'next-intl';
import { registerSchema, type RegisterInput } from '@travelbuddy/validation';
import { Alert, Button, FormField, Input } from '@travelbuddy/ui';
import { Link } from '@/i18n/navigation';
import { postAuth } from '@/lib/api-browser';

/**
 * Registration (dev identity). Collects what the platform needs for `POST /v1/auth/register`:
 * name, email, birth date (18+ gate, PRD AUTH-008; only the year is stored) and terms consent.
 */
export function RegisterForm({ next }: { next: string }) {
  const t = useTranslations('auth.register');
  const tv = useTranslations();
  const locale = useLocale();
  const [serverError, setServerError] = useState<string | null>(null);
  const { register, handleSubmit, formState } = useForm<RegisterInput>({
    resolver: zodResolver(registerSchema),
    defaultValues: { display_name: '', email: '', birth_date: '' },
  });
  const err = (key?: string) => (key ? tv(key as Parameters<typeof tv>[0]) : undefined);

  const onSubmit = handleSubmit(async (values) => {
    setServerError(null);
    const res = await postAuth<{ redirect?: string; code?: string }>('/api/auth/dev', { mode: 'register', ...values, next, locale });
    if (res.ok && res.data.redirect) {
      window.location.assign(res.data.redirect);
      return;
    }
    const code = res.data.code;
    setServerError(
      code === 'age_restricted'
        ? t('errors.ageRestricted')
        : code === 'conflict'
          ? t('errors.exists')
          : code === 'consent_required'
            ? t('errors.consentChanged')
            : t('errors.generic'),
    );
  });

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      {serverError ? <Alert tone="danger">{serverError}</Alert> : null}
      <FormField id="display_name" label={t('displayName')} error={err(formState.errors.display_name?.message)} required>
        <Input autoComplete="name" {...register('display_name')} />
      </FormField>
      <FormField id="email" label={t('email')} error={err(formState.errors.email?.message)} required>
        <Input type="email" autoComplete="email" {...register('email')} />
      </FormField>
      <FormField id="birth_date" label={t('birthDate')} hint={t('birthDateHint')} error={err(formState.errors.birth_date?.message)} required>
        <Input type="date" autoComplete="bday" {...register('birth_date')} />
      </FormField>
      <div className="flex flex-col gap-1.5">
        <label className="flex items-start gap-3 text-sm">
          <input type="checkbox" className="mt-0.5 size-4 accent-[var(--tb-primary)]" aria-invalid={formState.errors.terms_accepted ? true : undefined} {...register('terms_accepted')} />
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
        {formState.errors.terms_accepted ? (
          <p role="alert" className="text-xs font-medium text-danger">
            {err(formState.errors.terms_accepted.message)}
          </p>
        ) : null}
      </div>
      <Button type="submit" size="lg" loading={formState.isSubmitting}>
        {t('submit')}
      </Button>
    </form>
  );
}
