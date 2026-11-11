import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';

import type { MessageFilterPolicy } from '../api/types';
import { useSession } from '../auth/session';
import { Button, Card, ErrorNotice, Field, Loading } from '../components/ui';
import { useI18n } from '../i18n/I18n';

export function SafetyPage() {
  const { t } = useI18n();
  const { api } = useSession();
  const policy = useQuery({ queryKey: ['message-filter'], queryFn: api.messageFilter });
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t('safety.title')}</h1>
        </div>
      </div>
      {policy.isPending && <Loading />}
      {policy.isError && <ErrorNotice error={policy.error} onRetry={() => void policy.refetch()} />}
      {policy.data && <FilterForm key={policy.data.version} policy={policy.data} />}
    </>
  );
}

function FilterForm({ policy }: { policy: MessageFilterPolicy }) {
  const { t, dateTime } = useI18n();
  const { api } = useSession();
  const queryClient = useQueryClient();
  const [terms, setTerms] = useState(policy.terms.join('\n'));
  const [days, setDays] = useState(policy.new_connection_days);
  const save = useMutation({
    mutationFn: () =>
      api.updateMessageFilter({
        terms: terms
          .split('\n')
          .map((term) => term.trim())
          .filter(Boolean),
        new_connection_days: days,
        version: policy.version,
      }),
    onSuccess: (updated) => queryClient.setQueryData(['message-filter'], updated),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    save.mutate();
  };
  return (
    <form className="two-col" onSubmit={submit}>
      <Card>
        <p className="muted">{t('safety.help')}</p>
        <Field label={t('safety.terms')}>
          {(props) => (
            <textarea {...props} rows={14} value={terms} onChange={(e) => setTerms(e.target.value)} />
          )}
        </Field>
        <Field label={t('safety.days')}>
          {(props) => (
            <input
              {...props}
              type="number"
              min={0}
              max={365}
              value={days}
              onChange={(e) => setDays(Number(e.target.value) || 0)}
            />
          )}
        </Field>
        {save.isError && <ErrorNotice error={save.error} />}
        {save.isSuccess && (
          <div className="notice success" role="status">
            {t('safety.saved')}
          </div>
        )}
        <div className="row spread">
          <span className="muted">
            {policy.updated_at ? t('safety.updated', { when: dateTime(policy.updated_at) }) : ''}
          </span>
          <Button type="submit" variant="primary" disabled={save.isPending}>
            {t('common.save')}
          </Button>
        </div>
      </Card>
      <Card title={t('safety.defaults')}>
        <pre className="evidence">{policy.default_terms.join('\n')}</pre>
        <Button
          onClick={() => {
            setTerms(policy.default_terms.join('\n'));
            setDays(policy.default_new_connection_days);
          }}
        >
          {t('safety.useDefaults')}
        </Button>
      </Card>
    </form>
  );
}
