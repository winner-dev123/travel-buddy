import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router';

import { useSession } from '../auth/session';
import { Badge, Card, ErrorNotice, Loading, Stat } from '../components/ui';
import { useI18n } from '../i18n/I18n';

export function OverviewPage() {
  const { t, number, age, money, dateTime } = useI18n();
  const { api, can } = useSession();
  const overview = useQuery({ queryKey: ['overview'], queryFn: api.overview, refetchInterval: 60_000 });
  const ops = useQuery({
    queryKey: ['ops'],
    queryFn: api.ops,
    enabled: can('audit.read'),
    refetchInterval: 60_000,
  });

  return (
    <>
      <div className="page-head">
        <div>
          <span className="overline">{t('app.console')}</span>
          <h1>{t('overview.title')}</h1>
        </div>
        {overview.data && (
          <span className="muted">
            {t('overview.updated', { time: dateTime(overview.data.generated_at) })}
          </span>
        )}
      </div>

      {overview.isPending && <Loading />}
      {overview.isError && <ErrorNotice error={overview.error} onRetry={() => void overview.refetch()} />}

      {overview.data && (
        <>
          <div className="grid">
            <Stat
              label={t('overview.reports')}
              value={number(overview.data.moderation.open_reports)}
              sub={
                overview.data.moderation.open_reports === 0 ? (
                  t('overview.queueClear')
                ) : (
                  <span className="stack" style={{ gap: 2 }}>
                    <span>{t('overview.unassigned', { count: overview.data.moderation.unassigned_reports })}</span>
                    {overview.data.moderation.oldest_open_age_seconds !== null && (
                      <span>
                        {t('overview.oldest', { age: age(overview.data.moderation.oldest_open_age_seconds) })}
                      </span>
                    )}
                    {can('moderation.reports.read') && <Link to="/reports">{t('overview.openQueue')}</Link>}
                  </span>
                )
              }
            />
            <Stat
              label={t('overview.accounts')}
              value={number(overview.data.users.total)}
              sub={t('overview.newWeek', { count: number(overview.data.users.new_7d) })}
            />
            <Stat label={t('overview.active')} value={number(overview.data.users.active_7d)} />
            <Stat label={t('overview.premium')} value={number(overview.data.premium_members)} />
            <Stat label={t('overview.posts')} value={number(overview.data.posts_7d)} />
            <Stat label={t('overview.suspended')} value={number(overview.data.users.suspended)} />
            {overview.data.open_data_requests !== null && (
              <Stat label={t('overview.privacy')} value={number(overview.data.open_data_requests)} />
            )}
          </div>

          {overview.data.revenue_30d !== null && (
            <Card title={t('overview.revenue')}>
              <p className="muted">{t('overview.revenueNote')}</p>
              {overview.data.revenue_30d.length === 0 ? (
                <p className="muted">{t('overview.noRevenue')}</p>
              ) : (
                <div className="row" style={{ gap: 28 }}>
                  {overview.data.revenue_30d.map((r) => (
                    <div
                      key={`${r.environment}-${r.currency}`}
                      className="stack"
                      style={{ gap: 4, alignItems: 'flex-start' }}
                    >
                      <span className="stat-value">{money(r.amount_minor, r.currency)}</span>
                      {r.environment === 'sandbox' && <Badge tone="warning">{t('overview.testMode')}</Badge>}
                    </div>
                  ))}
                </div>
              )}
            </Card>
          )}
        </>
      )}

      {ops.data && (
        <Card title={t('overview.system')}>
          <dl className="facts">
            <dt>{t('overview.outbox')}</dt>
            <dd>
              {number(ops.data.outbox.unpublished_events ?? 0)}
              {ops.data.outbox.oldest_unpublished_age_seconds
                ? ` · ${age(ops.data.outbox.oldest_unpublished_age_seconds)}`
                : ''}
            </dd>
            <dt>{t('overview.jobsDue')}</dt>
            <dd>
              {number(ops.data.jobs.queued_due ?? 0)}
              {ops.data.jobs.oldest_due_age_seconds ? ` · ${age(ops.data.jobs.oldest_due_age_seconds)}` : ''}
            </dd>
          </dl>
        </Card>
      )}
    </>
  );
}
