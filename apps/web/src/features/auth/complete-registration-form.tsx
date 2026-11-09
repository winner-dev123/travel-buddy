'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useTranslations } from 'next-intl';
import { completeRegistrationSchema, type CompleteRegistrationInput } from '@travelbuddy/validation';
import { Alert, Button, FormField, Input } from '@travelbuddy/ui';
import { postAuth } from '@/lib/api-browser';
import { authErrorKey } from './auth-errors';
import { ConsentCheckbox } from './consent-checkbox';

/** Age gate and consent for an IdP identity that has no platform account yet (AUTH-008). */
export function CompleteRegistrationForm() {
  const t = useTranslations('auth');
  const tv = useTranslations();
  const [serverError, setServerError] = useState<string | null>(null);
  const { register, handleSubmit, formState } = useForm<CompleteRegistrationInput>({
    resolver: zodResolver(completeRegistrationSchema),
    defaultValues: { birth_date: '' },
  });
  const err = (key?: string) => (key ? tv(key as Parameters<typeof tv>[0]) : undefined);

  const onSubmit = handleSubmit(async (values) => {
    setServerError(null);
    const res = await postAuth<{ redirect?: string; code?: string }>('/api/auth/complete', values);
    if (res.ok && res.data.redirect) {
      window.location.assign(res.data.redirect);
      return;
    }
    setServerError(t(`errors.${authErrorKey(res.data.code)}`));
  });

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      {serverError ? <Alert tone="danger">{serverError}</Alert> : null}
      <FormField id="birth_date" label={t('register.birthDate')} hint={t('register.birthDateHint')} error={err(formState.errors.birth_date?.message)} required>
        <Input type="date" autoComplete="bday" {...register('birth_date')} />
      </FormField>
      <ConsentCheckbox registration={register('terms_accepted')} error={err(formState.errors.terms_accepted?.message)} />
      <Button type="submit" size="lg" loading={formState.isSubmitting}>
        {t('complete.submit')}
      </Button>
    </form>
  );
}
