'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useTranslations } from 'next-intl';
import { resetPasswordSchema, type ResetPasswordInput } from '@travelbuddy/validation';
import { Alert, Button, FormField, Input } from '@travelbuddy/ui';
import { postAuth } from '@/lib/api-browser';
import { authErrorKey } from './auth-errors';

/** Chooses a new password after a recovery link, then signs in. */
export function ResetPasswordForm() {
  const t = useTranslations('auth');
  const tv = useTranslations();
  const [serverError, setServerError] = useState<string | null>(null);
  const { register, handleSubmit, formState } = useForm<ResetPasswordInput>({
    resolver: zodResolver(resetPasswordSchema),
    defaultValues: { password: '', confirm: '' },
  });
  const err = (key?: string) => (key ? tv(key as Parameters<typeof tv>[0]) : undefined);

  const onSubmit = handleSubmit(async (values) => {
    setServerError(null);
    const res = await postAuth<{ redirect?: string; code?: string }>('/api/auth/reset-password', values);
    if (res.ok && res.data.redirect) {
      window.location.assign(res.data.redirect);
      return;
    }
    setServerError(t(`errors.${authErrorKey(res.data.code)}`));
  });

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      {serverError ? <Alert tone="danger">{serverError}</Alert> : null}
      <FormField id="new-password" label={t('reset.password')} hint={t('register.passwordHint')} error={err(formState.errors.password?.message)} required>
        <Input type="password" autoComplete="new-password" {...register('password')} />
      </FormField>
      <FormField id="confirm-password" label={t('reset.confirm')} error={err(formState.errors.confirm?.message)} required>
        <Input type="password" autoComplete="new-password" {...register('confirm')} />
      </FormField>
      <Button type="submit" size="lg" loading={formState.isSubmitting}>
        {t('reset.submit')}
      </Button>
    </form>
  );
}
