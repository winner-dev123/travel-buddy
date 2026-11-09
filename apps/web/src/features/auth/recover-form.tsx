'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useLocale, useTranslations } from 'next-intl';
import { z } from 'zod';
import { emailSchema } from '@travelbuddy/validation';
import { Alert, Button, FormField, Input } from '@travelbuddy/ui';
import { postAuth } from '@/lib/api-browser';
import { authErrorKey } from './auth-errors';

const schema = z.object({ email: emailSchema });

/** Requests a password-recovery email. The answer is the same whether or not the account exists. */
export function RecoverForm() {
  const t = useTranslations('auth');
  const tv = useTranslations();
  const locale = useLocale();
  const [sent, setSent] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);
  const { register, handleSubmit, formState } = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema), defaultValues: { email: '' } });
  const err = (key?: string) => (key ? tv(key as Parameters<typeof tv>[0]) : undefined);

  const onSubmit = handleSubmit(async (values) => {
    setServerError(null);
    const res = await postAuth<{ ok?: boolean; code?: string }>('/api/auth/recover', { ...values, locale });
    if (res.ok) setSent(true);
    else setServerError(t(`errors.${authErrorKey(res.data.code)}`));
  });

  if (sent) return <Alert tone="success">{t('forgot.sent')}</Alert>;
  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      {serverError ? <Alert tone="danger">{serverError}</Alert> : null}
      <FormField id="recover-email" label={t('forgot.email')} error={err(formState.errors.email?.message)} required>
        <Input type="email" autoComplete="email" {...register('email')} />
      </FormField>
      <Button type="submit" size="lg" loading={formState.isSubmitting}>
        {t('forgot.submit')}
      </Button>
    </form>
  );
}
