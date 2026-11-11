import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router';

import { usePaged } from '../api/hooks';
import { PLATFORM_ROLES, REPORT_REASONS, type AdminUser, type PlatformRole } from '../api/types';
import { useSession } from '../auth/session';
import {
  AccountStatusBadge,
  Badge,
  Button,
  Card,
  Dialog,
  Empty,
  ErrorNotice,
  Field,
  Loading,
  LoadMore,
  TransactionStatusBadge,
} from '../components/ui';
import { useI18n } from '../i18n/I18n';

const SUSPEND_DAYS = [1, 3, 7, 30, 0];

export function UserDetailPage() {
  const { id = '' } = useParams();
  const { t, date, dateTime, money } = useI18n();
  const { api, can } = useSession();
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState<'suspend' | 'reinstate' | 'grant' | null>(null);

  const user = useQuery({ queryKey: ['user', id], queryFn: () => api.user(id) });
  const grants = useQuery({
    queryKey: ['grants', id],
    queryFn: () => api.grants(id),
    enabled: can('entitlements.grant'),
  });
  const payments = usePaged(
    ['transactions', { user_id: id }],
    (cursor) => api.transactions({ user_id: id }, cursor),
    can('entitlements.grant'),
  );
  const history = usePaged(
    ['actions', 'user', id],
    (cursor) => api.actions('user', id, cursor),
    can('moderation.actions.read'),
  );
  const privacy = usePaged(
    ['data-requests', { user_id: id, state: 'all' }],
    (cursor) => api.dataRequests({ user_id: id, state: 'all' }, cursor),
    can('privacy.requests.manage'),
  );

  const setUser = (updated: AdminUser) => {
    queryClient.setQueryData(['user', id], updated);
    void queryClient.invalidateQueries({ queryKey: ['users'] });
    void queryClient.invalidateQueries({ queryKey: ['actions', 'user', id] });
    void queryClient.invalidateQueries({ queryKey: ['overview'] });
  };
  const revoke = useMutation({
    mutationFn: (grantId: string) => api.revokeGrant(grantId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['grants', id] }),
  });
  const role = useMutation({
    mutationFn: ({ name, give }: { name: PlatformRole; give: boolean }) =>
      give ? api.assignRole(id, name) : api.removeRole(id, name),
    onSuccess: setUser,
  });

  if (user.isPending) return <Loading />;
  if (user.isError) return <ErrorNotice error={user.error} onRetry={() => void user.refetch()} />;
  const u = user.data;
  const restricted = u.status === 'suspended' || u.status === 'deactivated';

  return (
    <>
      <div className="page-head">
        <div>
          <Link to="/users">← {t('users.title')}</Link>
          <h1>{u.display_name}</h1>
          <div className="row">
            <span className="muted">@{u.handle}</span>
            <AccountStatusBadge status={u.status} />
            {u.roles.map((r) => (
              <Badge key={r} tone="accent">
                {t(`role.${r}`)}
              </Badge>
            ))}
          </div>
        </div>
        {can('users.suspend') && (
          <div className="row">
            {u.status === 'active' && (
              <Button variant="danger" onClick={() => setDialog('suspend')}>
                {t('user.suspend')}
              </Button>
            )}
            {restricted && <Button onClick={() => setDialog('reinstate')}>{t('user.reinstate')}</Button>}
          </div>
        )}
      </div>

      <div className="two-col">
        <div className="stack">
          {can('entitlements.grant') && (
            <Card
              title={t('user.premium')}
              actions={
                u.status === 'active' && (
                  <Button small variant="primary" onClick={() => setDialog('grant')}>
                    {t('user.givePremium')}
                  </Button>
                )
              }
            >
              {grants.isPending && <Loading />}
              {grants.isError && <ErrorNotice error={grants.error} />}
              {grants.data && grants.data.data.length === 0 && <Empty>{t('user.noGrants')}</Empty>}
              {grants.data?.data.map((grant) => (
                <div key={grant.id} className="row spread">
                  <span>
                    <strong>Premium</strong>{' '}
                    {grant.ends_at ? t('user.until', { date: date(grant.ends_at) }) : ''}
                  </span>
                  {grant.revoked_at ? (
                    <Badge>{t('user.revoked')}</Badge>
                  ) : (
                    <Button small onClick={() => revoke.mutate(grant.id)} disabled={revoke.isPending}>
                      {t('user.revoke')}
                    </Button>
                  )}
                </div>
              ))}
              {revoke.isError && <ErrorNotice error={revoke.error} />}
            </Card>
          )}

          {can('entitlements.grant') && (
            <Card title={t('user.payments')}>
              {payments.isPending && <Loading />}
              {payments.isError && <ErrorNotice error={payments.error} />}
              {payments.isSuccess && payments.items.length === 0 && <Empty>{t('user.noPayments')}</Empty>}
              {payments.items.length > 0 && (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>{t('billing.col.when')}</th>
                        <th>{t('billing.col.product')}</th>
                        <th className="num">{t('billing.col.amount')}</th>
                        <th>{t('billing.col.provider')}</th>
                        <th>{t('billing.col.status')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {payments.items.map((tx) => (
                        <tr key={tx.id}>
                          <td>{dateTime(tx.occurred_at)}</td>
                          <td>
                            {t(`txKind.${tx.kind}`)}
                            {tx.product?.title ? ` · ${tx.product.title}` : ''}
                          </td>
                          <td className="num">
                            {tx.amount_minor !== null && tx.currency ? money(tx.amount_minor, tx.currency) : '—'}
                          </td>
                          <td>
                            {t(`provider.${tx.provider}`)}
                            {tx.environment === 'sandbox' && <> <Badge tone="warning">{t('billing.test')}</Badge></>}
                          </td>
                          <td>
                            <TransactionStatusBadge status={tx.status} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <LoadMore
                hasMore={Boolean(payments.hasNextPage)}
                loading={payments.isFetchingNextPage}
                onClick={() => void payments.fetchNextPage()}
              />
            </Card>
          )}

          {can('moderation.actions.read') && (
            <Card title={t('user.history')}>
              {history.isPending && <Loading />}
              {history.isError && <ErrorNotice error={history.error} />}
              {history.isSuccess && history.items.length === 0 && <Empty>{t('user.noHistory')}</Empty>}
              {history.items.map((action) => (
                <div key={action.id} className="row spread">
                  <span>
                    <strong>{t(`action.${action.action}`)}</strong> · {action.reason_code}
                    {action.notes ? ` · ${action.notes}` : ''}
                  </span>
                  <span className="muted">{dateTime(action.created_at)}</span>
                </div>
              ))}
            </Card>
          )}

          {can('privacy.requests.manage') && (
            <Card title={t('user.privacy')}>
              {privacy.isPending && <Loading />}
              {privacy.isError && <ErrorNotice error={privacy.error} />}
              {privacy.isSuccess && privacy.items.length === 0 && <Empty>{t('user.noPrivacy')}</Empty>}
              {privacy.items.map((request) => (
                <div key={request.id} className="row spread">
                  <span>
                    <strong>{t(`dataKind.${request.kind}`)}</strong> · {t(`dataStatus.${request.status}`)}
                    {request.overdue && <> <Badge tone="danger">{t('privacy.overdue')}</Badge></>}
                  </span>
                  <span className="muted">{dateTime(request.requested_at)}</span>
                </div>
              ))}
            </Card>
          )}
        </div>

        <div className="stack">
          <Card>
            <dl className="facts">
              <dt>{t('user.email')}</dt>
              <dd className="mono">{u.email ?? '—'}</dd>
              <dt>{t('user.joined')}</dt>
              <dd>{date(u.created_at)}</dd>
              <dt>{t('user.lastActive')}</dt>
              <dd>{u.last_active_on ? date(u.last_active_on) : t('common.never')}</dd>
              <dt>{t('user.openReports')}</dt>
              <dd>{u.open_report_count}</dd>
              <dt>{t('user.actions')}</dt>
              <dd>{u.moderation_action_count}</dd>
              {u.suspended_until && (
                <>
                  <dt>{t('user.suspendedUntil')}</dt>
                  <dd>{dateTime(u.suspended_until)}</dd>
                </>
              )}
              <dt>ID</dt>
              <dd className="mono">{u.id}</dd>
            </dl>
          </Card>

          {can('roles.assign') && (
            <Card title={t('user.roles')}>
              <p className="muted">{t('user.rolesHelp')}</p>
              {PLATFORM_ROLES.map((name) => {
                const has = u.roles.includes(name);
                return (
                  <label key={name} className="choice">
                    <input
                      type="checkbox"
                      checked={has}
                      disabled={role.isPending || (!has && u.status !== 'active')}
                      onChange={() => role.mutate({ name, give: !has })}
                    />
                    {t(`role.${name}`)}
                  </label>
                );
              })}
              {role.isError && <ErrorNotice error={role.error} />}
            </Card>
          )}
        </div>
      </div>

      <SuspendDialog user={u} open={dialog === 'suspend'} onClose={() => setDialog(null)} onDone={setUser} />
      <ReinstateDialog user={u} open={dialog === 'reinstate'} onClose={() => setDialog(null)} onDone={setUser} />
      <GrantDialog
        userId={u.id}
        open={dialog === 'grant'}
        onClose={() => setDialog(null)}
        onDone={() => void queryClient.invalidateQueries({ queryKey: ['grants', id] })}
      />
    </>
  );
}

function SuspendDialog({
  user,
  open,
  onClose,
  onDone,
}: {
  user: AdminUser;
  open: boolean;
  onClose: () => void;
  onDone: (user: AdminUser) => void;
}) {
  const { t } = useI18n();
  const { api } = useSession();
  const [reason, setReason] = useState<string>('harassment');
  const [notes, setNotes] = useState('');
  const [days, setDays] = useState(7);
  const suspend = useMutation({
    mutationFn: () =>
      api.suspend(user.id, {
        reason_code: reason,
        notes: notes.trim(),
        until: days > 0 ? new Date(Date.now() + days * 86_400_000).toISOString() : null,
      }),
    onSuccess: (updated) => {
      onDone(updated);
      onClose();
    },
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    suspend.mutate();
  };
  return (
    <Dialog open={open} title={t('suspend.title')} onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <div className="notice warning">{t('suspend.warning')}</div>
        <Field label={t('suspend.reason')}>
          {(props) => (
            <select {...props} value={reason} onChange={(e) => setReason(e.target.value)}>
              {REPORT_REASONS.map((r) => (
                <option key={r} value={r}>
                  {t(`reportReason.${r}`)}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label={t('suspend.for')}>
          {(props) => (
            <select {...props} value={days} onChange={(e) => setDays(Number(e.target.value))}>
              {SUSPEND_DAYS.map((d) => (
                <option key={d} value={d}>
                  {d === 0 ? t('resolve.untilLifted') : t('resolve.days', { count: d })}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label={t('suspend.notes')}>
          {(props) => (
            <textarea
              {...props}
              required
              minLength={3}
              maxLength={2000}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          )}
        </Field>
        {suspend.isError && <ErrorNotice error={suspend.error} />}
        <div className="dialog-actions">
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button type="submit" variant="danger" disabled={suspend.isPending || notes.trim().length < 3}>
            {t('suspend.submit')}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function ReinstateDialog({
  user,
  open,
  onClose,
  onDone,
}: {
  user: AdminUser;
  open: boolean;
  onClose: () => void;
  onDone: (user: AdminUser) => void;
}) {
  const { t } = useI18n();
  const { api } = useSession();
  const [notes, setNotes] = useState('');
  const reinstate = useMutation({
    mutationFn: () => api.reinstate(user.id, notes.trim()),
    onSuccess: (updated) => {
      onDone(updated);
      onClose();
    },
  });
  return (
    <Dialog open={open} title={t('reinstate.title')} onClose={onClose}>
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          reinstate.mutate();
        }}
      >
        <Field label={t('reinstate.notes')}>
          {(props) => (
            <textarea
              {...props}
              required
              minLength={3}
              maxLength={1000}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          )}
        </Field>
        {reinstate.isError && <ErrorNotice error={reinstate.error} />}
        <div className="dialog-actions">
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button type="submit" variant="primary" disabled={reinstate.isPending || notes.trim().length < 3}>
            {t('reinstate.submit')}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function GrantDialog({
  userId,
  open,
  onClose,
  onDone,
}: {
  userId: string;
  open: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  const { t } = useI18n();
  const { api } = useSession();
  const [days, setDays] = useState(30);
  const [reason, setReason] = useState('');
  const grant = useMutation({
    mutationFn: () =>
      api.grant(userId, {
        entitlement_key: 'premium',
        ends_at: new Date(Date.now() + days * 86_400_000).toISOString(),
        reason: reason.trim(),
      }),
    onSuccess: () => {
      onDone();
      onClose();
    },
  });
  return (
    <Dialog open={open} title={t('grant.title')} onClose={onClose}>
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          grant.mutate();
        }}
      >
        <Field label={t('grant.days')}>
          {(props) => (
            <input
              {...props}
              type="number"
              min={1}
              max={366}
              required
              value={days}
              onChange={(e) => setDays(Math.max(1, Math.min(366, Number(e.target.value) || 1)))}
            />
          )}
        </Field>
        <Field label={t('grant.reason')} hint={t('reason.hint')}>
          {(props) => (
            <textarea
              {...props}
              required
              minLength={10}
              maxLength={500}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          )}
        </Field>
        {grant.isError && <ErrorNotice error={grant.error} />}
        <div className="dialog-actions">
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button type="submit" variant="primary" disabled={grant.isPending || reason.trim().length < 10}>
            {t('grant.submit')}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
