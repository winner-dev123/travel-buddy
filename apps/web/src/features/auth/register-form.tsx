'use client';

import { useState } from 'react';
import { useForm, type Resolver } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useLocale, useTranslations } from 'next-intl';
import { z } from 'zod';
import { passwordRegisterSchema, registerSchema, type RegisterInput } from '@travelbuddy/validation';
import { Alert, Button, FormField, Input } from '@travelbuddy/ui';
import { postAuth } from '@/lib/api-browser';
import { authErrorKey } from './auth-errors';
import { ConsentCheckbox } from './consent-checkbox';

type FormValues = RegisterInput & { password?: string };
const devRegisterSchema = registerSchema.extend({ password: z.string().optional() });

/**
 * Registration. Collects what the platform needs for `POST /v1/auth/register` — name, email,
 * birth date (18+ gate, PRD AUTH-008; only the year is stored) and terms consent — plus a password
 * when the identity provider is Supabase Auth (`withPassword`, ADR-0020). Without it, the
 * development identity provider is used.
 */
export function RegisterForm({ next, withPassword = false }: { next: string; withPassword?: boolean }) {
  const t = useTranslations('auth');
  const tv = useTranslations();
  const locale = useLocale();
  const [serverError, setServerError] = useState<string | null>(null);
  // Same field set either way; the password is only validated and sent in Supabase mode.
  const { register, handleSubmit, formState } = useForm<FormValues>({
    resolver: zodResolver(withPassword ? passwordRegisterSchema : devRegisterSchema) as Resolver<FormValues>,
    defaultValues: { display_name: '', email: '', birth_date: '', password: '' },
  });
  const err = (key?: string) => (key ? tv(key as Parameters<typeof tv>[0]) : undefined);

  const onSubmit = handleSubmit(async ({ password, ...values }) => {
    setServerError(null);
    const res = withPassword
      ? await postAuth<{ redirect?: string; code?: string }>('/api/auth/signup', { ...values, password, next, locale })
      : await postAuth<{ redirect?: string; code?: string }>('/api/auth/dev', { mode: 'register', ...values, next, locale });
    if (res.ok && res.data.redirect) {
      window.location.assign(res.data.redirect);
      return;
    }
    const code = res.data.code;
    setServerError(
      code === 'conflict'
        ? t('register.errors.exists')
        : code === 'consent_required'
          ? t('register.errors.consentChanged')
          : code === 'age_restricted'
            ? t('register.errors.ageRestricted')
            : authErrorKey(code) === 'generic'
              ? t('register.errors.generic')
              : t(`errors.${authErrorKey(code)}`),
    );
  });

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      {serverError ? <Alert tone="danger">{serverError}</Alert> : null}
      <FormField id="display_name" label={t('register.displayName')} error={err(formState.errors.display_name?.message)} required>
        <Input autoComplete="name" {...register('display_name')} />
      </FormField>
      <FormField id="email" label={t('register.email')} error={err(formState.errors.email?.message)} required>
        <Input type="email" autoComplete="email" {...register('email')} />
      </FormField>
      {withPassword ? (
        <FormField id="password" label={t('register.password')} hint={t('register.passwordHint')} error={err(formState.errors.password?.message)} required>
          <Input type="password" autoComplete="new-password" {...register('password')} />
        </FormField>
      ) : null}
      <FormField id="birth_date" label={t('register.birthDate')} hint={t('register.birthDateHint')} error={err(formState.errors.birth_date?.message)} required>
        <Input type="date" autoComplete="bday" {...register('birth_date')} />
      </FormField>
      <ConsentCheckbox registration={register('terms_accepted')} error={err(formState.errors.terms_accepted?.message)} />
      <Button type="submit" size="lg" loading={formState.isSubmitting}>
        {t('register.submit')}
      </Button>
    </form>
  );
}
