import { useNavigate, useSearchParams } from 'react-router';

import { usePaged } from '../api/hooks';
import { REPORT_REASONS, REPORT_STATUSES, REPORT_TARGET_TYPES, type ReportStatus } from '../api/types';
import { useSession } from '../auth/session';
import {
  Badge,
  Empty,
  ErrorNotice,
  Field,
  Loading,
  LoadMore,
  Person,
  PriorityBadge,
  ReportStatusBadge,
} from '../components/ui';
import { useNow } from '../hooks/useNow';
import { useI18n } from '../i18n/I18n';

export function ReportsPage() {
  const { t, age } = useI18n();
  const { api } = useSession();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const filters = {
    status: (params.get('status') ?? 'open') as ReportStatus | '',
    reason: params.get('reason') ?? '',
    target_type: params.get('target_type') ?? '',
    assigned_to: params.get('assigned_to') ?? '',
  };
  const setFilter = (name: keyof typeof filters, value: string) => {
    const next = new URLSearchParams(params);
    next.set(name, value);
    setParams(next, { replace: true });
  };
  const reports = usePaged(['reports', filters], (cursor) =>
    api.reports(
      {
        status: filters.status || undefined,
        reason: filters.reason || undefined,
        target_type: filters.target_type || undefined,
        assigned_to: filters.assigned_to || undefined,
      },
      cursor,
    ),
  );
  const now = useNow();

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t('reports.title')}</h1>
        </div>
      </div>

      <div className="filters">
        <Field label={t('reports.status')}>
          {(props) => (
            <select {...props} value={filters.status} onChange={(e) => setFilter('status', e.target.value)}>
              <option value="">{t('common.all')}</option>
              {REPORT_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {t(`reportStatus.${s}`)}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label={t('reports.reason')}>
          {(props) => (
            <select {...props} value={filters.reason} onChange={(e) => setFilter('reason', e.target.value)}>
              <option value="">{t('common.all')}</option>
              {REPORT_REASONS.map((r) => (
                <option key={r} value={r}>
                  {t(`reportReason.${r}`)}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label={t('reports.target')}>
          {(props) => (
            <select
              {...props}
              value={filters.target_type}
              onChange={(e) => setFilter('target_type', e.target.value)}
            >
              <option value="">{t('common.all')}</option>
              {REPORT_TARGET_TYPES.map((type) => (
                <option key={type} value={type}>
                  {t(`target.${type}`)}
                </option>
              ))}
            </select>
          )}
        </Field>
        <Field label={t('reports.assigned')}>
          {(props) => (
            <select
              {...props}
              value={filters.assigned_to}
              onChange={(e) => setFilter('assigned_to', e.target.value)}
            >
              <option value="">{t('common.all')}</option>
              <option value="me">{t('reports.assigned.me')}</option>
              <option value="unassigned">{t('reports.assigned.unassigned')}</option>
            </select>
          )}
        </Field>
      </div>

      {reports.isPending && <Loading />}
      {reports.isError && <ErrorNotice error={reports.error} onRetry={() => void reports.refetch()} />}
      {reports.isSuccess && reports.items.length === 0 && <Empty>{t('reports.empty')}</Empty>}
      {reports.items.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t('reports.col.priority')}</th>
                <th>{t('reports.col.reason')}</th>
                <th>{t('reports.col.target')}</th>
                <th>{t('reports.col.reporter')}</th>
                <th>{t('reports.col.age')}</th>
                <th>{t('reports.col.status')}</th>
                <th>{t('reports.col.assignee')}</th>
              </tr>
            </thead>
            <tbody>
              {reports.items.map((report) => (
                <tr
                  key={report.id}
                  className="clickable"
                  tabIndex={0}
                  onClick={() => navigate(`/reports/${report.id}`)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') navigate(`/reports/${report.id}`);
                  }}
                >
                  <td>
                    <PriorityBadge priority={report.priority} />
                  </td>
                  <td>
                    <span className="row" style={{ gap: 6 }}>
                      {t(`reportReason.${report.reason}`)}
                      {report.related_report_count > 0 && <Badge>+{report.related_report_count}</Badge>}
                    </span>
                  </td>
                  <td>{t(`target.${report.target_type}`)}</td>
                  <td>
                    <Person person={report.reporter} />
                  </td>
                  <td>{age((now - Date.parse(report.created_at)) / 1000)}</td>
                  <td>
                    <ReportStatusBadge status={report.status} />
                  </td>
                  <td>{report.assigned_to ? <Person person={report.assigned_to} /> : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <LoadMore
        hasMore={Boolean(reports.hasNextPage)}
        loading={reports.isFetchingNextPage}
        onClick={() => void reports.fetchNextPage()}
      />
    </>
  );
}
