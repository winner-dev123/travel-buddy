import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router';

import { usePaged } from '../api/hooks';
import type { AdminDataRequest } from '../api/types';
import { useSession } from '../auth/session';
import { Badge, Button, Dialog, Empty, ErrorNotice, Field, Loading, LoadMore } from '../components/ui';
import { useI18n } from '../i18n/I18n';

const STATES = ['open', 'closed', 'all'] as const;

export function PrivacyPage() {
  const { t, date } = useI18n();
  const { api } = useSession();
  const [params, setParams] = useSearchParams();
  const state = (params.get('state') ?? 'open') as (typeof STATES)[number];
  const [closing, setClosing] = useState<AdminDataRequest | null>(null);
  const requests = usePaged(['data-requests', { state }], (cursor) => api.dataRequests({ state }, cursor));

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t('privacy.title')}</h1>
          <p className="muted">{t('privacy.help')}</p>
        </div>
        <div className="row" role="group" aria-label={t('privacy.kind')}>
          {STATES.map((s) => (
            <Button
              key={s}
              small
              variant={s === state ? 'primary' : 'default'}
              aria-pressed={s === state}
              onClick={() => setParams({ state: s }, { replace: true })}
            >
              {t(`privacy.state.${s}`)}
            </Button>
          ))}
        </div>
      </div>

      {requests.isPending && <Loading />}
      {requests.isError && <ErrorNotice error={requests.error} onRetry={() => void requests.refetch()} />}
      {requests.isSuccess && requests.items.length === 0 && <Empty>{t('privacy.empty')}</Empty>}
      {requests.items.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t('privacy.col.account')}</th>
                <th>{t('privacy.col.kind')}</th>
                <th>{t('privacy.col.channel')}</th>
                <th>{t('privacy.col.received')}</th>
                <th>{t('privacy.col.due')}</th>
                <th>{t('privacy.col.status')}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {requests.items.map((request) => {
                const open = request.status === 'received' || request.status === 'processing';
                return (
                  <tr key={request.id}>
                    <td>
                      <Link to={`/users/${request.user_id}`} className="mono">
                        {request.user_id.slice(0, 8)}
                      </Link>
                    </td>
                    <td>
                      {t(`dataKind.${request.kind}`)}
                      {request.details && <div className="muted">{request.details}</div>}
                    </td>
                    <td>{t(`channel.${request.channel}`)}</td>
                    <td>{date(request.requested_at)}</td>
                    <td>
                      {date(request.due_at)}{' '}
                      {request.overdue && <Badge tone="danger">{t('privacy.overdue')}</Badge>}
                    </td>
                    <td>{t(`dataStatus.${request.status}`)}</td>
                    <td>
                      {open && request.channel !== 'app' && (
                        <Button small onClick={() => setClosing(request)}>
                          {t('privacy.close')}
                        </Button>
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
        hasMore={Boolean(requests.hasNextPage)}
        loading={requests.isFetchingNextPage}
        onClick={() => void requests.fetchNextPage()}
      />
      {closing && <CloseDialog request={closing} onClose={() => setClosing(null)} />}
    </>
  );
}

function CloseDialog({ request, onClose }: { request: AdminDataRequest; onClose: () => void }) {
  const { t } = useI18n();
  const { api } = useSession();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<'completed' | 'rejected'>('completed');
  const [resolution, setResolution] = useState('');
  const resolve = useMutation({
    mutationFn: () => api.resolveDataRequest(request.id, { status, resolution: resolution.trim() }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['data-requests'] });
      void queryClient.invalidateQueries({ queryKey: ['overview'] });
      onClose();
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    resolve.mutate();
  };
  return (
    <Dialog open title={t('privacy.resolveTitle')} onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <label className="choice">
          <input type="radio" checked={status === 'completed'} onChange={() => setStatus('completed')} />
          {t('privacy.completed')}
        </label>
        <label className="choice">
          <input type="radio" checked={status === 'rejected'} onChange={() => setStatus('rejected')} />
          {t('privacy.rejected')}
        </label>
        <Field label={t('privacy.resolution')}>
          {(props) => (
            <textarea
              {...props}
              required
              minLength={3}
              maxLength={2000}
              value={resolution}
              onChange={(e) => setResolution(e.target.value)}
            />
          )}
        </Field>
        {resolve.isError && <ErrorNotice error={resolve.error} />}
        <div className="dialog-actions">
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button type="submit" variant="primary" disabled={resolve.isPending || resolution.trim().length < 3}>
            {t('privacy.close')}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
