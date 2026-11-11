import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router';

import type { ResolveReportBody } from '../api/admin';
import {
  REPORT_REASONS,
  RESTRICTION_KINDS,
  type AdminReport,
  type ModerationActionRequest,
  type ModerationActionType,
  type RestrictionKind,
} from '../api/types';
import { useSession } from '../auth/session';
import {
  Badge,
  Button,
  Card,
  Dialog,
  Empty,
  ErrorNotice,
  Field,
  Loading,
  Person,
  PriorityBadge,
  ReportStatusBadge,
} from '../components/ui';
import { useI18n } from '../i18n/I18n';

const CONTENT_ACTIONS: ModerationActionType[] = ['remove_content', 'limit_visibility'];
const ACCOUNT_ACTIONS: ModerationActionType[] = ['warn', 'restrict', 'suspend', 'ban'];
const DURATIONS = [1, 3, 7, 30, 0];

export function ReportDetailPage() {
  const { id = '' } = useParams();
  const { t, dateTime } = useI18n();
  const { api, can, state } = useSession();
  const queryClient = useQueryClient();
  const [resolving, setResolving] = useState(false);
  const report = useQuery({ queryKey: ['report', id], queryFn: () => api.report(id) });
  const history = useQuery({
    queryKey: ['actions', report.data?.target_type, report.data?.target_id],
    queryFn: () => api.actions(report.data!.target_type, report.data!.target_id),
    enabled: Boolean(report.data) && can('moderation.actions.read'),
  });
  const myId = state.status === 'signed_in' ? state.me.account.id : '';

  const refresh = (updated: AdminReport) => {
    queryClient.setQueryData(['report', id], updated);
    void queryClient.invalidateQueries({ queryKey: ['reports'] });
    void queryClient.invalidateQueries({ queryKey: ['overview'] });
    void queryClient.invalidateQueries({ queryKey: ['actions'] });
  };
  const assign = useMutation({ mutationFn: () => api.assignReport(id, myId), onSuccess: refresh });

  if (report.isPending) return <Loading />;
  if (report.isError) return <ErrorNotice error={report.error} onRetry={() => void report.refetch()} />;
  const r = report.data;
  const waiting = r.status === 'open' || r.status === 'in_review';
  const manage = can('moderation.reports.manage');
  const author = r.target_type === 'user' ? { id: r.target_id } : r.target_author;

  return (
    <>
      <div className="page-head">
        <div>
          <Link to="/reports">← {t('reports.title')}</Link>
          <h1>
            {t(`reportReason.${r.reason}`)} · {t(`target.${r.target_type}`)}
          </h1>
          <div className="row">
            <PriorityBadge priority={r.priority} />
            <ReportStatusBadge status={r.status} />
            {r.related_report_count > 0 && <Badge>{t('report.related', { count: r.related_report_count })}</Badge>}
          </div>
        </div>
        {waiting && manage && (
          <div className="row">
            {r.assigned_to?.id !== myId && (
              <Button onClick={() => assign.mutate()} disabled={assign.isPending}>
                {t('report.assign')}
              </Button>
            )}
            <Button variant="primary" onClick={() => setResolving(true)}>
              {t('report.resolve')}
            </Button>
          </div>
        )}
      </div>

      {r.reason === 'minor_safety' && (
        <div className="notice danger" role="alert">
          {t('report.childSafety')}
        </div>
      )}
      {assign.isError && <ErrorNotice error={assign.error} />}

      <div className="two-col">
        <div className="stack">
          <Card title={t('report.evidence')}>
            {typeof r.evidence.body === 'string' && <p style={{ whiteSpace: 'pre-wrap' }}>{r.evidence.body}</p>}
            <pre className="evidence">{JSON.stringify(r.evidence, null, 2)}</pre>
          </Card>
          {r.details && (
            <Card title={t('report.note')}>
              <p style={{ whiteSpace: 'pre-wrap' }}>{r.details}</p>
            </Card>
          )}
          {can('moderation.actions.read') && (
            <Card title={t('report.history')}>
              {history.isPending && <Loading />}
              {history.isError && <ErrorNotice error={history.error} />}
              {history.data && history.data.data.length === 0 && <Empty>{t('report.noHistory')}</Empty>}
              {history.data?.data.map((action) => (
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
        </div>
        <Card>
          <dl className="facts">
            <dt>{t('report.reportedAt')}</dt>
            <dd>{dateTime(r.created_at)}</dd>
            <dt>{t('report.reportedBy')}</dt>
            <dd>
              <Person person={r.reporter} />
            </dd>
            <dt>{t('report.author')}</dt>
            <dd className="stack" style={{ gap: 4 }}>
              {r.target_author ? <Person person={r.target_author} /> : <span className="muted">—</span>}
              {author && can('users.read') && <Link to={`/users/${author.id}`}>{t('report.openAccount')}</Link>}
            </dd>
            <dt>{t('report.assignedTo')}</dt>
            <dd>{r.assigned_to ? <Person person={r.assigned_to} /> : t('report.unassigned')}</dd>
            {r.resolution_note && (
              <>
                <dt>{t('report.resolution')}</dt>
                <dd>{r.resolution_note}</dd>
              </>
            )}
            <dt>ID</dt>
            <dd className="mono">{r.target_id}</dd>
          </dl>
        </Card>
      </div>

      <ResolveDialog
        report={r}
        authorId={author?.id ?? null}
        open={resolving}
        onClose={() => setResolving(false)}
        onResolved={(updated) => {
          refresh(updated);
          setResolving(false);
        }}
      />
    </>
  );
}

function ResolveDialog({
  report,
  authorId,
  open,
  onClose,
  onResolved,
}: {
  report: AdminReport;
  authorId: string | null;
  open: boolean;
  onClose: () => void;
  onResolved: (report: AdminReport) => void;
}) {
  const { t } = useI18n();
  const { api, can } = useSession();
  const [outcome, setOutcome] = useState<'actioned' | 'dismissed'>('actioned');
  const [note, setNote] = useState('');
  const [action, setAction] = useState<ModerationActionType | ''>('');
  const [policy, setPolicy] = useState<string>(report.reason);
  const [restriction, setRestriction] = useState<RestrictionKind>('messaging_limited');
  const [days, setDays] = useState(7);
  const [notes, setNotes] = useState('');

  const contentTarget = report.target_type !== 'user';
  const available = [
    ...(contentTarget ? CONTENT_ACTIONS : []),
    ...(authorId ? ACCOUNT_ACTIONS.filter((a) => a !== 'ban' || can('users.ban')) : []),
  ];
  const timed = action === 'suspend' || action === 'restrict';

  const resolve = useMutation({
    mutationFn: (body: ResolveReportBody) => api.resolveReport(report.id, body),
    onSuccess: onResolved,
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    let moderation: ModerationActionRequest | undefined;
    if (outcome === 'actioned' && action) {
      const onAccount = ACCOUNT_ACTIONS.includes(action);
      moderation = {
        target_type: onAccount ? 'user' : report.target_type,
        target_id: onAccount ? (authorId as string) : report.target_id,
        action,
        reason_code: policy,
        report_id: report.id,
        ...(action === 'restrict' ? { restriction_kind: restriction } : {}),
        ...(timed && days > 0
          ? { expires_at: new Date(Date.now() + days * 86_400_000).toISOString() }
          : {}),
        ...(notes.trim() ? { notes: notes.trim() } : {}),
      };
    }
    resolve.mutate({ status: outcome, resolution_note: note.trim(), action: moderation });
  };

  return (
    <Dialog open={open} title={t('resolve.title')} onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="label" style={{ fontWeight: 700, fontSize: 13 }}>
            {t('resolve.outcome')}
          </legend>
          <label className="choice">
            <input type="radio" checked={outcome === 'actioned'} onChange={() => setOutcome('actioned')} />
            {t('resolve.actioned')}
          </label>
          <label className="choice">
            <input type="radio" checked={outcome === 'dismissed'} onChange={() => setOutcome('dismissed')} />
            {t('resolve.dismissed')}
          </label>
        </fieldset>

        {outcome === 'actioned' && (
          <>
            <Field label={t('resolve.action')}>
              {(props) => (
                <select
                  {...props}
                  value={action}
                  onChange={(e) => setAction(e.target.value as ModerationActionType | '')}
                >
                  <option value="">{t('resolve.noAction')}</option>
                  {available.map((a) => (
                    <option key={a} value={a}>
                      {t(`action.${a}`)}
                    </option>
                  ))}
                </select>
              )}
            </Field>
            {action && (
              <Field label={t('resolve.policy')}>
                {(props) => (
                  <select {...props} value={policy} onChange={(e) => setPolicy(e.target.value)}>
                    {REPORT_REASONS.map((reason) => (
                      <option key={reason} value={reason}>
                        {t(`reportReason.${reason}`)}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
            )}
            {action === 'restrict' && (
              <Field label={t('resolve.restriction')}>
                {(props) => (
                  <select
                    {...props}
                    value={restriction}
                    onChange={(e) => setRestriction(e.target.value as RestrictionKind)}
                  >
                    {RESTRICTION_KINDS.map((kind) => (
                      <option key={kind} value={kind}>
                        {t(`restriction.${kind}`)}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
            )}
            {timed && (
              <Field label={t('resolve.duration')}>
                {(props) => (
                  <select {...props} value={days} onChange={(e) => setDays(Number(e.target.value))}>
                    {DURATIONS.map((d) => (
                      <option key={d} value={d}>
                        {d === 0 ? t('resolve.untilLifted') : t('resolve.days', { count: d })}
                      </option>
                    ))}
                  </select>
                )}
              </Field>
            )}
            {action && (
              <Field label={t('resolve.notes')}>
                {(props) => (
                  <textarea {...props} maxLength={2000} value={notes} onChange={(e) => setNotes(e.target.value)} />
                )}
              </Field>
            )}
          </>
        )}

        <Field label={t('resolve.note')}>
          {(props) => (
            <textarea
              {...props}
              required
              minLength={3}
              maxLength={2000}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          )}
        </Field>
        {resolve.isError && <ErrorNotice error={resolve.error} />}
        <div className="dialog-actions">
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button type="submit" variant="primary" disabled={resolve.isPending || note.trim().length < 3}>
            {t('resolve.submit')}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
