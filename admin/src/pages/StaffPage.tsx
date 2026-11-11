import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router';

import { usePaged } from '../api/hooks';
import { PLATFORM_ROLES, type AdminUserSummary, type PlatformRole } from '../api/types';
import { useSession } from '../auth/session';
import { Button, Card, Empty, ErrorNotice, Field, Loading } from '../components/ui';
import { useI18n } from '../i18n/I18n';
import { UserTable } from './UsersPage';

export function StaffPage() {
  const { t } = useI18n();
  const { api } = useSession();
  const navigate = useNavigate();
  const staff = usePaged(['users', 'staff'], (cursor) => api.users({ staff: true }, cursor));
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t('staff.title')}</h1>
          <p className="muted" style={{ maxWidth: 760 }}>
            {t('staff.help')}
          </p>
        </div>
      </div>
      <AddStaff />
      {staff.isPending && <Loading />}
      {staff.isError && <ErrorNotice error={staff.error} onRetry={() => void staff.refetch()} />}
      {staff.isSuccess && staff.items.length === 0 && <Empty>{t('staff.empty')}</Empty>}
      {staff.items.length > 0 && <UserTable users={staff.items} onOpen={(id) => navigate(`/users/${id}`)} />}
    </>
  );
}

function AddStaff() {
  const { t } = useI18n();
  const { api } = useSession();
  const queryClient = useQueryClient();
  const [query, setQuery] = useState('');
  const [found, setFound] = useState<AdminUserSummary[] | null>(null);
  const [chosen, setChosen] = useState<string>('');
  const [role, setRole] = useState<PlatformRole>('moderator');
  const search = useMutation({
    mutationFn: () => api.users({ q: query.trim() }),
    onSuccess: (page) => {
      setFound(page.data);
      setChosen(page.data[0]?.id ?? '');
    },
  });
  const give = useMutation({
    mutationFn: () => api.assignRole(chosen, role),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['users'] });
      setFound(null);
      setQuery('');
    },
  });
  const find = (event: FormEvent) => {
    event.preventDefault();
    if (query.trim()) search.mutate();
  };
  return (
    <Card title={t('staff.add')}>
      <form className="filters" onSubmit={find} role="search">
        <Field label={t('staff.find')} className="grow">
          {(props) => <input {...props} type="search" value={query} onChange={(e) => setQuery(e.target.value)} />}
        </Field>
        <Button type="submit" disabled={search.isPending || !query.trim()}>
          {t('common.search')}
        </Button>
      </form>
      {search.isError && <ErrorNotice error={search.error} />}
      {found && found.length === 0 && <p className="muted">{t('users.empty')}</p>}
      {found && found.length > 0 && (
        <form
          className="filters"
          onSubmit={(event) => {
            event.preventDefault();
            if (chosen) give.mutate();
          }}
        >
          <Field label={t('users.col.name')} className="grow">
            {(props) => (
              <select {...props} value={chosen} onChange={(e) => setChosen(e.target.value)}>
                {found.map((user) => (
                  <option key={user.id} value={user.id} disabled={user.status !== 'active'}>
                    {user.display_name} (@{user.handle})
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label={t('staff.role')}>
            {(props) => (
              <select {...props} value={role} onChange={(e) => setRole(e.target.value as PlatformRole)}>
                {PLATFORM_ROLES.map((r) => (
                  <option key={r} value={r}>
                    {t(`role.${r}`)}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Button type="submit" variant="primary" disabled={give.isPending || !chosen}>
            {t('staff.give')}
          </Button>
        </form>
      )}
      {give.isError && <ErrorNotice error={give.error} />}
      {give.isSuccess && (
        <div className="notice success" role="status">
          {t('staff.added')}
        </div>
      )}
    </Card>
  );
}
