import { useState, type FormEvent } from 'react';

import { usePaged } from '../api/hooks';
import { useSession } from '../auth/session';
import { Button, Empty, ErrorNotice, Field, Loading, LoadMore } from '../components/ui';
import { useI18n } from '../i18n/I18n';

interface AuditFilters {
  resource_type: string;
  resource_id: string;
  actor_id: string;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function AuditPage() {
  const { t, dateTime } = useI18n();
  const { api } = useSession();
  const [draft, setDraft] = useState<AuditFilters>({ resource_type: '', resource_id: '', actor_id: '' });
  const [filters, setFilters] = useState<AuditFilters>(draft);
  const entries = usePaged(['audit', filters], (cursor) =>
    api.auditLogs(
      {
        resource_type: filters.resource_type || undefined,
        resource_id: filters.resource_id || undefined,
        actor_id: filters.actor_id || undefined,
      },
      cursor,
    ),
  );
  const invalidId = (value: string) => Boolean(value) && !UUID.test(value);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (invalidId(draft.resource_id) || invalidId(draft.actor_id)) return;
    setFilters({
      resource_type: draft.resource_type.trim(),
      resource_id: draft.resource_id.trim(),
      actor_id: draft.actor_id.trim(),
    });
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t('audit.title')}</h1>
          <p className="muted">{t('audit.help')}</p>
        </div>
      </div>
      <form className="filters" onSubmit={submit}>
        <Field label={t('audit.resourceType')}>
          {(props) => (
            <input
              {...props}
              placeholder="user"
              maxLength={60}
              value={draft.resource_type}
              onChange={(e) => setDraft({ ...draft, resource_type: e.target.value })}
            />
          )}
        </Field>
        <Field label={t('audit.resourceId')} error={invalidId(draft.resource_id) ? 'UUID' : undefined}>
          {(props) => (
            <input
              {...props}
              value={draft.resource_id}
              onChange={(e) => setDraft({ ...draft, resource_id: e.target.value.trim() })}
            />
          )}
        </Field>
        <Field label={t('audit.actorId')} error={invalidId(draft.actor_id) ? 'UUID' : undefined}>
          {(props) => (
            <input
              {...props}
              value={draft.actor_id}
              onChange={(e) => setDraft({ ...draft, actor_id: e.target.value.trim() })}
            />
          )}
        </Field>
        <Button type="submit" variant="primary">
          {t('common.search')}
        </Button>
      </form>

      {entries.isPending && <Loading />}
      {entries.isError && <ErrorNotice error={entries.error} onRetry={() => void entries.refetch()} />}
      {entries.isSuccess && entries.items.length === 0 && <Empty>{t('audit.empty')}</Empty>}
      {entries.items.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t('audit.col.when')}</th>
                <th>{t('audit.col.who')}</th>
                <th>{t('audit.col.action')}</th>
                <th>{t('audit.col.resource')}</th>
                <th>{t('audit.col.reason')}</th>
                <th>{t('audit.details')}</th>
              </tr>
            </thead>
            <tbody>
              {entries.items.map((entry) => {
                const { justification, ...details } = entry.metadata as { justification?: unknown };
                return (
                  <tr key={entry.id}>
                    <td style={{ whiteSpace: 'nowrap' }}>{dateTime(entry.occurred_at)}</td>
                    <td>
                      {t(`actor.${entry.actor_type}`)}
                      {entry.actor_id && <div className="mono muted">{entry.actor_id.slice(0, 8)}</div>}
                    </td>
                    <td className="mono">{entry.action}</td>
                    <td>
                      {entry.resource_type}
                      {entry.resource_id && <div className="mono muted">{entry.resource_id.slice(0, 8)}</div>}
                    </td>
                    <td>{typeof justification === 'string' ? justification : '—'}</td>
                    <td>
                      {Object.keys(details).length > 0 && (
                        <details>
                          <summary>{t('audit.details')}</summary>
                          <pre className="evidence">{JSON.stringify(details, null, 2)}</pre>
                        </details>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      <LoadMore
        hasMore={Boolean(entries.hasNextPage)}
        loading={entries.isFetchingNextPage}
        onClick={() => void entries.fetchNextPage()}
      />
    </>
  );
}
