'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useLocale, useTranslations } from 'next-intl';
import { emailSignInSchema, type EmailSignInInput } from '@travelbuddy/validation';
import { Alert, Button, FormField, Input } from '@travelbuddy/ui';
import { postAuth } from '@/lib/api-browser';
import { authErrorKey } from './auth-errors';

/** Email + password sign-in (Supabase Auth through the BFF, ADR-0020). */
export function EmailSignInForm({ next }: { next: string }) {
  const t = useTranslations('auth');
  const tv = useTranslations();
  const locale = useLocale();
  const [serverError, setServerError] = useState<string | null>(null);
  const { register, handleSubmit, formState } = useForm<EmailSignInInput>({
    resolver: zodResolver(emailSignInSchema),
    defaultValues: { email: '', password: '' },
  });
  const err = (key?: string) => (key ? tv(key as Parameters<typeof tv>[0]) : undefined);

  const onSubmit = handleSubmit(async (values) => {
    setServerError(null);
    const res = await postAuth<{ redirect?: string; code?: string }>('/api/auth/password', { ...values, next, locale });
    if (res.ok && res.data.redirect) {
      window.location.assign(res.data.redirect);
      return;
    }
    setServerError(t(`errors.${authErrorKey(res.data.code)}`));
  });

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4" aria-label={t('login.emailFormLabel')}>
      {serverError ? <Alert tone="danger">{serverError}</Alert> : null}
      <FormField id="signin-email" label={t('login.email')} error={err(formState.errors.email?.message)} required>
        <Input type="email" autoComplete="email" {...register('email')} />
      </FormField>
      <FormField id="signin-password" label={t('login.password')} error={err(formState.errors.password?.message)} required>
        <Input type="password" autoComplete="current-password" {...register('password')} />
      </FormField>
      <Button type="submit" size="lg" loading={formState.isSubmitting}>
        {t('login.submit')}
      </Button>
    </form>
  );
}
