import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router';

import { usePaged } from '../api/hooks';
import { TRANSACTION_STATUSES } from '../api/types';
import { useSession } from '../auth/session';
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorNotice,
  Field,
  Loading,
  LoadMore,
  TransactionStatusBadge,
} from '../components/ui';
import { useI18n } from '../i18n/I18n';

export function BillingPage() {
  const { t } = useI18n();
  const { can } = useSession();
  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t('billing.title')}</h1>
        </div>
      </div>
      <Transactions />
      {can('billing.configure') && <Plans />}
    </>
  );
}

function Transactions() {
  const { t, dateTime, money } = useI18n();
  const { api } = useSession();
  const [params, setParams] = useSearchParams();
  const status = params.get('status') ?? '';
  const ledger = usePaged(['transactions', { status }], (cursor) =>
    api.transactions({ status: status || undefined }, cursor),
  );
  return (
    <Card title={t('billing.transactions')}>
      <div className="filters">
        <Field label={t('billing.status')}>
          {(props) => (
            <select
              {...props}
              value={status}
              onChange={(e) => {
                const next = new URLSearchParams(params);
                if (e.target.value) next.set('status', e.target.value);
                else next.delete('status');
                setParams(next, { replace: true });
              }}
            >
              <option value="">{t('common.all')}</option>
              {TRANSACTION_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {t(`txStatus.${s}`)}
                </option>
              ))}
            </select>
          )}
        </Field>
      </div>
      {ledger.isPending && <Loading />}
      {ledger.isError && <ErrorNotice error={ledger.error} onRetry={() => void ledger.refetch()} />}
      {ledger.isSuccess && ledger.items.length === 0 && <Empty>{t('billing.empty')}</Empty>}
      {ledger.items.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t('billing.col.when')}</th>
                <th>{t('billing.col.account')}</th>
                <th>{t('billing.col.product')}</th>
                <th className="num">{t('billing.col.amount')}</th>
                <th>{t('billing.col.provider')}</th>
                <th>{t('billing.col.status')}</th>
                <th>{t('billing.col.reference')}</th>
              </tr>
            </thead>
            <tbody>
              {ledger.items.map((tx) => (
                <tr key={tx.id}>
                  <td>{dateTime(tx.occurred_at)}</td>
                  <td>
                    {tx.user_id ? (
                      <Link to={`/users/${tx.user_id}`} className="mono">
                        {tx.user_id.slice(0, 8)}
                      </Link>
                    ) : (
                      <span className="muted">{t('common.deletedAccount')}</span>
                    )}
                  </td>
                  <td>
                    {t(`txKind.${tx.kind}`)}
                    {tx.product?.title ? ` · ${tx.product.title}` : ''}
                  </td>
                  <td className="num">
                    {tx.amount_minor !== null && tx.currency ? money(tx.amount_minor, tx.currency) : '—'}
                  </td>
                  <td>
                    {t(`provider.${tx.provider}`)}
                    {tx.environment === 'sandbox' && (
                      <>
                        {' '}
                        <Badge tone="warning">{t('billing.test')}</Badge>
                      </>
                    )}
                  </td>
                  <td>
                    <TransactionStatusBadge status={tx.status} />
                  </td>
                  <td className="mono muted">{tx.provider_reference}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <LoadMore
        hasMore={Boolean(ledger.hasNextPage)}
        loading={ledger.isFetchingNextPage}
        onClick={() => void ledger.fetchNextPage()}
      />
    </Card>
  );
}

function Plans() {
  const { t, locale } = useI18n();
  const { api } = useSession();
  const queryClient = useQueryClient();
  const products = useQuery({ queryKey: ['products'], queryFn: api.products });
  const toggle = useMutation({
    mutationFn: ({ id, active }: { id: string; active: boolean }) => api.updateProduct(id, { active }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['products'] }),
  });
  const title = (titles: Record<string, string> | undefined, sku: string) =>
    titles?.[locale] ?? titles?.en ?? sku;
  return (
    <Card title={t('billing.plans')}>
      <p className="muted">{t('billing.plans.help')}</p>
      {products.isPending && <Loading />}
      {products.isError && <ErrorNotice error={products.error} onRetry={() => void products.refetch()} />}
      {toggle.isError && <ErrorNotice error={toggle.error} />}
      {products.data && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t('billing.col.plan')}</th>
                <th>{t('billing.col.platform')}</th>
                <th>{t('billing.col.period')}</th>
                <th>{t('billing.col.sku')}</th>
                <th>{t('billing.col.active')}</th>
              </tr>
            </thead>
            <tbody>
              {[...products.data.data]
                .sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || a.platform.localeCompare(b.platform))
                .map((product) => (
                  <tr key={product.id}>
                    <td>{title(product.title, product.sku)}</td>
                    <td>{t(`platform.${product.platform}`)}</td>
                    <td className="mono">{product.period ?? '—'}</td>
                    <td className="mono muted">{product.sku}</td>
                    <td>
                      <div className="row">
                        <Badge tone={product.active ? 'success' : 'neutral'}>
                          {product.active ? t('billing.onSale') : t('billing.offSale')}
                        </Badge>
                        <Button
                          small
                          disabled={toggle.isPending}
                          onClick={() => toggle.mutate({ id: product.id, active: !product.active })}
                        >
                          {product.active ? t('billing.turnOff') : t('billing.turnOn')}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
