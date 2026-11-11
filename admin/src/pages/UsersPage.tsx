import { useState, type FormEvent } from 'react';
import { useNavigate, useSearchParams } from 'react-router';

import { usePaged } from '../api/hooks';
import type { AccountStatus, AdminUserSummary } from '../api/types';
import { useSession } from '../auth/session';
import { AccountStatusBadge, Badge, Button, Empty, ErrorNotice, Field, Loading, LoadMore } from '../components/ui';
import { useI18n } from '../i18n/I18n';

const STATUSES: AccountStatus[] = ['active', 'suspended', 'deactivated', 'pending_deletion'];

export function UserTable({ users, onOpen }: { users: AdminUserSummary[]; onOpen: (id: string) => void }) {
  const { t, date } = useI18n();
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>{t('users.col.name')}</th>
            <th>{t('users.col.status')}</th>
            <th>{t('users.col.roles')}</th>
            <th>{t('users.col.joined')}</th>
            <th>{t('users.col.lastActive')}</th>
          </tr>
        </thead>
        <tbody>
          {users.map((user) => (
            <tr
              key={user.id}
              className="clickable"
              tabIndex={0}
              onClick={() => onOpen(user.id)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') onOpen(user.id);
              }}
            >
              <td>
                <span className="person">
                  <strong>{user.display_name}</strong>
                  <span>@{user.handle}</span>
                </span>
              </td>
              <td>
                <AccountStatusBadge status={user.status} />
              </td>
              <td>
                <span className="row" style={{ gap: 6 }}>
                  {user.roles.map((role) => (
                    <Badge key={role} tone="accent">
                      {t(`role.${role}`)}
                    </Badge>
                  ))}
                </span>
              </td>
              <td>{date(user.created_at)}</td>
              <td>{user.last_active_on ? date(user.last_active_on) : t('common.never')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function UsersPage() {
  const { t } = useI18n();
  const { api } = useSession();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const q = params.get('q') ?? '';
  const status = params.get('status') ?? '';
  const staff = params.get('staff') === 'true';
  const [draft, setDraft] = useState(q);

  const users = usePaged(['users', q, status, staff], (cursor) =>
    api.users({ q: q || undefined, status: status || undefined, staff: staff || undefined }, cursor),
  );

  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setParams(next, { replace: true });
  };

  const search = (event: FormEvent) => {
    event.preventDefault();
    update({ q: draft.trim() || null });
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t('users.title')}</h1>
          <p className="muted">{t('users.hint')}</p>
        </div>
      </div>
      <form className="filters" onSubmit={search} role="search">
        <Field label={t('common.search')} className="grow">
          {(props) => (
            <input
              {...props}
              type="search"
              placeholder={t('users.search')}
              value={draft}
              maxLength={320}
              onChange={(e) => setDraft(e.target.value)}
            />
          )}
        </Field>
        <Field label={t('users.status')}>
          {(props) => (
            <select {...props} value={status} onChange={(e) => update({ status: e.target.value || null })}>
              <option value="">{t('common.all')}</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {t(`accountStatus.${s}`)}
                </option>
              ))}
            </select>
          )}
        </Field>
        <label className="choice" style={{ minHeight: 40 }}>
          <input
            type="checkbox"
            checked={staff}
            onChange={(e) => update({ staff: e.target.checked ? 'true' : null })}
          />
          {t('users.staffOnly')}
        </label>
        <Button type="submit" variant="primary">
          {t('common.search')}
        </Button>
      </form>

      {users.isPending && <Loading />}
      {users.isError && <ErrorNotice error={users.error} onRetry={() => void users.refetch()} />}
      {users.isSuccess && users.items.length === 0 && <Empty>{t('users.empty')}</Empty>}
      {users.items.length > 0 && <UserTable users={users.items} onOpen={(id) => navigate(`/users/${id}`)} />}
      <LoadMore
        hasMore={Boolean(users.hasNextPage)}
        loading={users.isFetchingNextPage}
        onClick={() => void users.fetchNextPage()}
      />
    </>
  );
}
