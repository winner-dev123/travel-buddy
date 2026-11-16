import { useNavigate, useSearchParams } from 'react-router';

import { usePaged } from '../api/hooks';
import { PROVIDER_KINDS, PROVIDER_STATUSES, type ProviderKind, type ProviderStatus } from '../api/types';
import { useSession } from '../auth/session';
import { Empty, ErrorNotice, Field, Loading, LoadMore, Person, ProviderStatusBadge } from '../components/ui';
import { useI18n } from '../i18n/I18n';

/** A value from the URL, kept only when the API knows it (a hand-edited URL would get a 422). */
function known<T extends string>(value: string | null, allowed: readonly T[], fallback: T | ''): T | '' {
  if (value === null) return fallback;
  return (allowed as readonly string[]).includes(value) ? (value as T) : '';
}

export function ProvidersPage() {
  const { t, date, country } = useI18n();
  const { api } = useSession();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  // The review queue by default: submitted applications, oldest first.
  const filters = {
    status: known<ProviderStatus>(params.get('status'), PROVIDER_STATUSES, 'submitted'),
    kind: known<ProviderKind>(params.get('kind'), PROVIDER_KINDS, ''),
  };
  const setFilter = (name: keyof typeof filters, value: string) => {
    const next = new URLSearchParams(params);
    next.set(name, value);
    setParams(next, { replace: true });
  };
  const providers = usePaged(['providers', filters], (cursor) =>
    api.providers({ status: filters.status || undefined, kind: filters.kind || undefined }, cursor),
  );
  const open = (id: string) => navigate(`/providers/${id}`);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t('providers.title')}</h1>
          <p className="muted">{t('providers.help')}</p>
        </div>
      </div>

      <div className="filters">
        <Field label={t('providers.status')}>
          {(props) => (
            <select {...props} value={filters.status} onChange={(e) => setFilter('status', e.target.value)}>
              <option value="">{t('common.all')}</option>
              {PROVIDER_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {t(`providerStatus.${s}`)}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label={t('providers.kind')}>
          {(props) => (
            <select {...props} value={filters.kind} onChange={(e) => setFilter('kind', e.target.value)}>
              <option value="">{t('common.all')}</option>
              {PROVIDER_KINDS.map((k) => (
                <option key={k} value={k}>
                  {t(`providerKind.${k}`)}
                </option>
              ))}
            </select>
          )}
        </Field>
      </div>

      {providers.isPending && <Loading />}
      {providers.isError && <ErrorNotice error={providers.error} onRetry={() => void providers.refetch()} />}
      {providers.isSuccess && providers.items.length === 0 && <Empty>{t('providers.empty')}</Empty>}
      {providers.items.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t('providers.col.name')}</th>
                <th>{t('providers.col.kind')}</th>
                <th>{t('providers.col.country')}</th>
                <th>{t('providers.col.owner')}</th>
                <th>{t('providers.col.submitted')}</th>
                <th>{t('providers.col.decided')}</th>
                <th>{t('providers.col.status')}</th>
              </tr>
            </thead>
            <tbody>
              {providers.items.map((provider) => (
                <tr
                  key={provider.id}
                  className="clickable"
                  tabIndex={0}
                  onClick={() => open(provider.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') open(provider.id);
                  }}
                >
                  <td>
                    <strong>{provider.display_name}</strong>
                  </td>
                  <td>{t(`providerKind.${provider.kind}`)}</td>
                  <td>{country(provider.country_code)}</td>
                  <td>
                    <Person person={provider.owner} />
                  </td>
                  <td>{provider.submitted_at ? date(provider.submitted_at) : '—'}</td>
                  <td>{provider.decided_at ? date(provider.decided_at) : '—'}</td>
                  <td>
                    <ProviderStatusBadge status={provider.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <LoadMore
        hasMore={Boolean(providers.hasNextPage)}
        loading={providers.isFetchingNextPage}
        onClick={() => void providers.fetchNextPage()}
      />
    </>
  );
}
