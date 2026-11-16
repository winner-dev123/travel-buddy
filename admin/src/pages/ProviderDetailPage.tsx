import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router';

import { ApiError } from '../api/http';
import type {
  AdminProvider,
  AdminProviderDocument,
  DestinationSummary,
  ProviderDecision,
  ProviderDecisionRequest,
} from '../api/types';
import { useSession } from '../auth/session';
import {
  Badge,
  Button,
  Card,
  Dialog,
  DocumentStatusBadge,
  Empty,
  ErrorNotice,
  Field,
  Loading,
  Person,
  ProviderStatusBadge,
} from '../components/ui';
import { useNow } from '../hooks/useNow';
import { useI18n, type Translate } from '../i18n/I18n';

const DECISIONS: ProviderDecision[] = ['approve', 'request_changes', 'reject'];
const NOTE_MAX = 1000;
const SUSPEND_REASON_MIN = 3;
const SUSPEND_REASON_MAX = 1000;

type DocumentChoice = '' | 'accepted' | 'rejected';

/** Only web links become links; anything else from the applicant (javascript:, data:) stays text. */
function webUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.toString() : null;
  } catch {
    return null;
  }
}

function place(destination: DestinationSummary): string {
  return [destination.name, destination.region_name, destination.country_name].filter(Boolean).join(', ');
}

/** `2027-05-31` as that calendar day here (UTC midnight would show the day before in the Americas). */
function localDay(value: string): Date {
  return new Date(`${value}T00:00:00`);
}

function isoDay(ms: number): string {
  const day = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`;
}

function documentLabel(doc: AdminProviderDocument, t: Translate): string {
  return `${t(`documentKind.${doc.kind}`)}${doc.number ? ` · ${doc.number}` : ''}`;
}

export function ProviderDetailPage() {
  const { id = '' } = useParams();
  const { t, date, dateTime, number, country, language } = useI18n();
  const { api, can } = useSession();
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState<'suspend' | 'reinstate' | null>(null);
  // The application carries legal details (the API sends it no-store): drop it once the page closes.
  const detail = useQuery({ queryKey: ['provider', id], queryFn: () => api.provider(id), gcTime: 0 });

  const refresh = (updated: AdminProvider) => {
    queryClient.setQueryData(['provider', id], updated);
    void queryClient.invalidateQueries({ queryKey: ['providers'] });
  };
  // A 410 means the file is gone; show that without another (audited) read of the application.
  const fileGone = (documentId: string) =>
    queryClient.setQueryData<AdminProvider>(['provider', id], (old) =>
      old
        ? {
            ...old,
            documents: old.documents.map((doc) =>
              doc.id === documentId ? { ...doc, file_available: false } : doc,
            ),
          }
        : old,
    );

  if (detail.isPending) return <Loading />;
  if (detail.isError) return <ErrorNotice error={detail.error} onRetry={() => void detail.refetch()} />;
  const d = detail.data;
  const p = d.provider;
  const website = webUrl(p.website_url);
  const photos = [
    { label: t('provider.logo'), url: webUrl(p.logo?.url) },
    { label: t('provider.cover'), url: webUrl(p.cover?.url) },
  ].filter((photo) => photo.url);
  const team = d.members.filter((member) => member.role !== 'owner');

  return (
    <>
      <div className="page-head">
        <div>
          <Link to="/providers">← {t('providers.title')}</Link>
          <h1>{p.display_name}</h1>
          <div className="row">
            <Badge tone="accent">{t(`providerKind.${p.kind}`)}</Badge>
            <ProviderStatusBadge status={p.status} />
            {p.verified_at && (
              <Badge tone="success">{t('provider.verifiedSince', { date: date(p.verified_at) })}</Badge>
            )}
            {d.open_report_count > 0 && (
              <Badge tone="danger">{t('provider.openReports', { count: d.open_report_count })}</Badge>
            )}
          </div>
        </div>
        {(p.status === 'approved' || p.status === 'suspended') && (
          <div className="row">
            {p.status === 'approved' && (
              <Button variant="danger" onClick={() => setDialog('suspend')}>
                {t('provider.suspend')}
              </Button>
            )}
            {p.status === 'suspended' && (
              <Button variant="primary" onClick={() => setDialog('reinstate')}>
                {t('provider.reinstate')}
              </Button>
            )}
          </div>
        )}
      </div>

      {p.status === 'suspended' && p.suspended_reason && (
        <div className="notice warning">
          <strong>{t('provider.suspendedReason')}:</strong> {p.suspended_reason}
        </div>
      )}

      <div className="two-col">
        <div className="stack">
          <Card title={t('provider.profile')}>
            <p className="muted">{t('provider.profileHelp')}</p>
            <dl className="facts">
              <dt>{t('provider.tagline')}</dt>
              <dd>{p.tagline ?? '—'}</dd>
              <dt>{t('provider.about')}</dt>
              <dd style={{ whiteSpace: 'pre-wrap' }}>{p.about ?? '—'}</dd>
              <dt>{t('provider.base')}</dt>
              <dd>{p.base_destination ? place(p.base_destination) : '—'}</dd>
              {p.service_areas.length > 0 && (
                <>
                  <dt>{t('provider.areas')}</dt>
                  <dd>{p.service_areas.map(place).join(' · ')}</dd>
                </>
              )}
              <dt>{t('provider.languages')}</dt>
              <dd>{p.languages.map((code) => language(code)).join(', ') || '—'}</dd>
              <dt>{t('provider.specialties')}</dt>
              <dd>{p.specialties.map((s) => t(`specialty.${s}`)).join(', ') || '—'}</dd>
              {p.years_experience !== null && (
                <>
                  <dt>{t('provider.experience')}</dt>
                  <dd>{t('provider.years', { count: p.years_experience })}</dd>
                </>
              )}
              <dt>{t('provider.website')}</dt>
              <dd style={{ overflowWrap: 'anywhere' }}>
                {website ? (
                  <a href={website} target="_blank" rel="noopener noreferrer">
                    {p.website_url}
                  </a>
                ) : (
                  (p.website_url ?? '—')
                )}
              </dd>
              {photos.length > 0 && (
                <>
                  <dt>{t('provider.photos')}</dt>
                  <dd className="row">
                    {photos.map((photo) => (
                      <a key={photo.label} href={photo.url!} target="_blank" rel="noopener noreferrer">
                        {photo.label}
                      </a>
                    ))}
                  </dd>
                </>
              )}
              <dt>{t('provider.offerings')}</dt>
              <dd>{p.published_offering_count}</dd>
              {p.rating_average !== null && p.rating_count > 0 && (
                <>
                  <dt>{t('provider.rating')}</dt>
                  <dd>
                    {t('provider.ratingValue', {
                      rating: number(Math.round(p.rating_average * 10) / 10),
                      count: p.rating_count,
                    })}
                  </dd>
                </>
              )}
            </dl>
          </Card>

          <DocumentsCard detail={d} onFileGone={fileGone} />

          {p.status === 'submitted' && <DecisionCard detail={d} onDone={refresh} />}
        </div>

        <div className="stack">
          <Card title={t('provider.private')}>
            <p className="muted">{t('provider.privateHelp')}</p>
            <dl className="facts">
              <dt>{t('provider.legalName')}</dt>
              <dd>{p.legal_name ?? '—'}</dd>
              <dt>{t('provider.registration')}</dt>
              <dd className="mono">{p.registration_number ?? '—'}</dd>
              <dt>{t('provider.country')}</dt>
              <dd>
                {country(p.country_code)} ({p.country_code})
              </dd>
              {p.missing_for_submit.length > 0 && (
                <>
                  <dt>{t('provider.missing')}</dt>
                  <dd className="mono">{p.missing_for_submit.join(', ')}</dd>
                </>
              )}
              <dt>{t('provider.started')}</dt>
              <dd>{date(p.created_at)}</dd>
              <dt>{t('provider.submitted')}</dt>
              <dd>{p.submitted_at ? dateTime(p.submitted_at) : '—'}</dd>
              {p.decided_at && (
                <>
                  <dt>{t('provider.decided')}</dt>
                  <dd>{dateTime(p.decided_at)}</dd>
                </>
              )}
              {d.decided_by && (
                <>
                  <dt>{t('provider.decidedBy')}</dt>
                  <dd className="mono" style={{ overflowWrap: 'anywhere' }}>
                    {can('users.read') ? <Link to={`/users/${d.decided_by}`}>{d.decided_by}</Link> : d.decided_by}
                  </dd>
                </>
              )}
              {p.review_note && (
                <>
                  <dt>{t('provider.note')}</dt>
                  <dd style={{ whiteSpace: 'pre-wrap' }}>{p.review_note}</dd>
                </>
              )}
              <dt>{t('provider.reports')}</dt>
              <dd>{d.open_report_count}</dd>
              <dt>ID</dt>
              <dd className="mono" style={{ overflowWrap: 'anywhere' }}>
                {p.id}
              </dd>
            </dl>
          </Card>

          <Card title={t('provider.team')}>
            <dl className="facts">
              <dt>{t('provider.owner')}</dt>
              <dd className="stack" style={{ gap: 4 }}>
                <Person person={d.owner} />
                {d.owner && can('users.read') && <Link to={`/users/${d.owner.id}`}>{t('report.openAccount')}</Link>}
              </dd>
            </dl>
            {team.length === 0 && <Empty>{t('provider.noTeam')}</Empty>}
            {team.map((member, index) => (
              <div key={member.user?.id ?? `former-${index}`} className="row spread">
                <Person person={member.user} />
                <span className="row" style={{ gap: 6 }}>
                  <Badge>{t(`providerRole.${member.role}`)}</Badge>
                  {member.status === 'invited' ? (
                    <Badge tone="info">{t('memberStatus.invited')}</Badge>
                  ) : (
                    <span className="muted">
                      {t('provider.memberSince', { date: date(member.accepted_at ?? member.created_at) })}
                    </span>
                  )}
                </span>
              </div>
            ))}
          </Card>
        </div>
      </div>

      <SuspendDialog
        providerId={p.id}
        open={dialog === 'suspend'}
        onClose={() => setDialog(null)}
        onDone={refresh}
      />
      <ReinstateDialog
        providerId={p.id}
        open={dialog === 'reinstate'}
        onClose={() => setDialog(null)}
        onDone={refresh}
      />
    </>
  );
}

function DocumentsCard({
  detail,
  onFileGone,
}: {
  detail: AdminProvider;
  onFileGone: (documentId: string) => void;
}) {
  const { t, date, country } = useI18n();
  const { api } = useSession();
  const today = isoDay(useNow());
  const [opening, setOpening] = useState<string | null>(null);
  const [failure, setFailure] = useState<unknown>(null);

  // The signed link is used at once and never kept: not in the query cache, not in state.
  const openFile = async (doc: AdminProviderDocument) => {
    setOpening(doc.id);
    setFailure(null);
    try {
      const link = await api.providerDocumentFile(detail.provider.id, doc.id);
      window.open(link.url, '_blank', 'noopener,noreferrer');
    } catch (error) {
      if (error instanceof ApiError && error.status === 410) onFileGone(doc.id);
      setFailure(error);
    } finally {
      setOpening(null);
    }
  };

  const status = failure instanceof ApiError ? failure.status : null;

  return (
    <Card title={t('provider.documents')}>
      <p className="muted">{t('provider.documentsHelp')}</p>
      {failure !== null &&
        (status === 410 || status === 409 ? (
          <div className="notice warning" role="alert">
            {t(status === 410 ? 'provider.doc.gone' : 'provider.doc.processing')}
          </div>
        ) : (
          <ErrorNotice error={failure} />
        ))}
      {detail.documents.length === 0 ? (
        <Empty>{t('provider.noDocuments')}</Empty>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t('provider.doc.kind')}</th>
                <th>{t('provider.doc.number')}</th>
                <th>{t('provider.doc.country')}</th>
                <th>{t('provider.doc.expires')}</th>
                <th>{t('provider.doc.status')}</th>
                <th>{t('provider.doc.file')}</th>
                <th>
                  <span className="visually-hidden">{t('provider.doc.open')}</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {detail.documents.map((doc) => {
                const expired = doc.expires_on !== null && doc.expires_on < today;
                return (
                  <tr key={doc.id}>
                    <td>{t(`documentKind.${doc.kind}`)}</td>
                    <td className="mono">{doc.number ?? '—'}</td>
                    <td>{doc.issuing_country ? country(doc.issuing_country) : '—'}</td>
                    <td>
                      <span className="row" style={{ gap: 6 }}>
                        {doc.expires_on ? date(localDay(doc.expires_on)) : '—'}
                        {expired && <Badge tone="danger">{t('provider.doc.expired')}</Badge>}
                      </span>
                    </td>
                    <td>
                      <DocumentStatusBadge status={doc.status} />
                    </td>
                    <td>
                      {doc.file_available ? (
                        t('provider.doc.kept')
                      ) : (
                        <span className="muted">{t('provider.doc.deleted')}</span>
                      )}
                    </td>
                    <td>
                      {doc.file_available && (
                        <Button
                          small
                          aria-label={`${t('provider.doc.open')}: ${documentLabel(doc, t)}`}
                          disabled={opening !== null}
                          onClick={() => void openFile(doc)}
                        >
                          {opening === doc.id ? t('common.loading') : t('provider.doc.open')}
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
    </Card>
  );
}

function DecisionCard({ detail, onDone }: { detail: AdminProvider; onDone: (updated: AdminProvider) => void }) {
  const { t } = useI18n();
  const { api } = useSession();
  const [decision, setDecision] = useState<ProviderDecision>('approve');
  const [note, setNote] = useState('');
  const [choices, setChoices] = useState<Record<string, DocumentChoice>>({});
  const [tried, setTried] = useState(false);
  const noteRef = useRef<HTMLTextAreaElement>(null);
  const trimmed = note.trim();
  const noteMissing = decision !== 'approve' && trimmed.length === 0;

  const decide = useMutation({
    mutationFn: (body: ProviderDecisionRequest) => api.decideProvider(detail.provider.id, body),
    onSuccess: onDone,
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    // The applicant must be told what to change or why (the API refuses it too).
    if (noteMissing) {
      setTried(true);
      noteRef.current?.focus();
      return;
    }
    const documents = detail.documents.flatMap((doc) => {
      const status = choices[doc.id];
      return status ? [{ id: doc.id, status }] : [];
    });
    decide.mutate({
      decision,
      ...(trimmed ? { note: trimmed } : {}),
      ...(documents.length > 0 ? { documents } : {}),
    });
  };

  return (
    <Card title={t('decision.title')}>
      <form className="stack" noValidate onSubmit={submit}>
        <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="label" style={{ fontWeight: 700, fontSize: 13 }}>
            {t('decision.outcome')}
          </legend>
          {DECISIONS.map((value) => (
            <label key={value} className="choice">
              <input
                type="radio"
                name="provider-decision"
                checked={decision === value}
                onChange={() => setDecision(value)}
              />
              {t(`decision.${value}`)}
            </label>
          ))}
        </fieldset>

        {detail.documents.length > 0 && (
          <fieldset className="stack" style={{ border: 0, padding: 0, margin: 0 }}>
            <legend className="label" style={{ fontWeight: 700, fontSize: 13 }}>
              {t('decision.documents')}
            </legend>
            <p className="muted">{t('decision.documentsHelp')}</p>
            <div className="filters">
              {detail.documents.map((doc) => (
                <Field key={doc.id} label={documentLabel(doc, t)}>
                  {(props) => (
                    <select
                      {...props}
                      value={choices[doc.id] ?? ''}
                      onChange={(e) => setChoices({ ...choices, [doc.id]: e.target.value as DocumentChoice })}
                    >
                      <option value="">{t('decision.keep', { status: t(`documentStatus.${doc.status}`) })}</option>
                      <option value="accepted">{t('decision.accept')}</option>
                      <option value="rejected">{t('decision.rejectDocument')}</option>
                    </select>
                  )}
                </Field>
              ))}
            </div>
          </fieldset>
        )}

        <Field
          label={t('decision.note')}
          hint={t('decision.noteHint')}
          error={tried && noteMissing ? t('decision.noteRequired') : undefined}
        >
          {(props) => (
            <textarea
              {...props}
              ref={noteRef}
              required={decision !== 'approve'}
              maxLength={NOTE_MAX}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          )}
        </Field>
        {decide.isError && <ErrorNotice error={decide.error} />}
        <div className="row">
          <Button
            type="submit"
            variant={decision === 'reject' ? 'danger' : 'primary'}
            disabled={decide.isPending}
          >
            {t(`decision.submit.${decision}`)}
          </Button>
        </div>
      </form>
    </Card>
  );
}

function SuspendDialog({
  providerId,
  open,
  onClose,
  onDone,
}: {
  providerId: string;
  open: boolean;
  onClose: () => void;
  onDone: (updated: AdminProvider) => void;
}) {
  const { t } = useI18n();
  const { api } = useSession();
  const [reason, setReason] = useState('');
  const valid = reason.trim().length >= SUSPEND_REASON_MIN;
  const suspend = useMutation({
    mutationFn: () => api.suspendProvider(providerId, reason.trim()),
    onSuccess: (updated) => {
      onDone(updated);
      setReason('');
      onClose();
    },
  });
  return (
    <Dialog open={open} title={t('providerSuspend.title')} onClose={onClose}>
      <form
        className="stack"
        onSubmit={(event) => {
          event.preventDefault();
          if (valid) suspend.mutate();
        }}
      >
        <div className="notice warning">{t('providerSuspend.warning')}</div>
        <Field label={t('providerSuspend.reason')}>
          {(props) => (
            <textarea
              {...props}
              required
              minLength={SUSPEND_REASON_MIN}
              maxLength={SUSPEND_REASON_MAX}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          )}
        </Field>
        {suspend.isError && <ErrorNotice error={suspend.error} />}
        <div className="dialog-actions">
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button type="submit" variant="danger" disabled={suspend.isPending || !valid}>
            {t('providerSuspend.submit')}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function ReinstateDialog({
  providerId,
  open,
  onClose,
  onDone,
}: {
  providerId: string;
  open: boolean;
  onClose: () => void;
  onDone: (updated: AdminProvider) => void;
}) {
  const { t } = useI18n();
  const { api } = useSession();
  const reinstate = useMutation({
    mutationFn: () => api.reinstateProvider(providerId),
    onSuccess: (updated) => {
      onDone(updated);
      onClose();
    },
  });
  return (
    <Dialog open={open} title={t('providerReinstate.title')} onClose={onClose}>
      <div className="stack">
        <p>{t('providerReinstate.help')}</p>
        {reinstate.isError && <ErrorNotice error={reinstate.error} />}
        <div className="dialog-actions">
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button variant="primary" disabled={reinstate.isPending} onClick={() => reinstate.mutate()}>
            {t('providerReinstate.submit')}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
