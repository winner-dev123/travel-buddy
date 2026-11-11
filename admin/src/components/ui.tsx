import {
  useEffect,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type ReactElement,
  type ReactNode,
} from 'react';

import { ApiError } from '../api/http';
import type {
  AccountStatus,
  ReportStatus,
  TransactionStatus,
  UserSummary,
} from '../api/types';
import type { MessageKey } from '../i18n/en';
import { useI18n, type Translate } from '../i18n/I18n';

type Variant = 'primary' | 'danger' | 'quiet' | 'default';

export function Button({
  variant = 'default',
  small,
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; small?: boolean }) {
  const classes = ['button', variant !== 'default' ? variant : '', small ? 'small' : '', className ?? '']
    .filter(Boolean)
    .join(' ');
  return <button type="button" {...props} className={classes} />;
}

export type Tone = 'accent' | 'success' | 'warning' | 'danger' | 'info' | 'neutral';

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`badge ${tone === 'neutral' ? '' : tone}`}>{children}</span>;
}

export function Card({ title, actions, children }: { title?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="card">
      {(title || actions) && (
        <div className="row spread">
          {title && <h2>{title}</h2>}
          {actions && <div className="row">{actions}</div>}
        </div>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <section className="card" aria-label={label}>
      <span className="overline">{label}</span>
      <span className="stat-value">{value}</span>
      {sub && <span className="stat-sub">{sub}</span>}
    </section>
  );
}

export function Field({
  label,
  hint,
  error,
  className,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  className?: string;
  children: (props: { id: string; 'aria-describedby'?: string; 'aria-invalid'?: boolean }) => ReactElement;
}) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy = [hintId, errorId].filter(Boolean).join(' ') || undefined;
  return (
    <div className={`field ${className ?? ''}`}>
      <label htmlFor={id}>{label}</label>
      {children({ id, 'aria-describedby': describedBy, 'aria-invalid': error ? true : undefined })}
      {hint && (
        <span className="hint" id={hintId}>
          {hint}
        </span>
      )}
      {error && (
        <span className="error" id={errorId} role="alert">
          {error}
        </span>
      )}
    </div>
  );
}

export function errorMessage(error: unknown, t: Translate): string {
  if (error instanceof ApiError) {
    const known: Record<string, MessageKey> = {
      network_error: 'errors.network_error',
      forbidden: 'errors.forbidden',
      justification_required: 'errors.justification_required',
      not_found: 'errors.not_found',
      validation_failed: 'errors.validation_failed',
      mfa_required: 'errors.mfa_required',
      rate_limited: 'errors.rate_limited',
    };
    const key = known[error.code];
    const base = key ? t(key) : error.message || t('errors.generic');
    const fields = error.fieldErrors.map((f) => `${f.field}: ${f.message}`).join(' · ');
    return [base, fields].filter(Boolean).join(' ');
  }
  return t('errors.generic');
}

export function ErrorNotice({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useI18n();
  const requestId = error instanceof ApiError ? error.requestId : undefined;
  return (
    <div className="notice danger" role="alert">
      <div className="row spread">
        <span>{errorMessage(error, t)}</span>
        {onRetry && (
          <Button small onClick={onRetry}>
            {t('common.retry')}
          </Button>
        )}
      </div>
      {requestId && <span className="mono muted">{t('common.reference', { id: requestId })}</span>}
    </div>
  );
}

export function Loading() {
  const { t } = useI18n();
  return (
    <p className="muted" role="status">
      {t('common.loading')}
    </p>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="muted">{children}</p>;
}

export function LoadMore({
  hasMore,
  loading,
  onClick,
}: {
  hasMore: boolean;
  loading: boolean;
  onClick: () => void;
}) {
  const { t } = useI18n();
  if (!hasMore) return null;
  return (
    <div className="row" style={{ justifyContent: 'center' }}>
      <Button onClick={onClick} disabled={loading}>
        {loading ? t('common.loading') : t('common.loadMore')}
      </Button>
    </div>
  );
}

export function Person({ person }: { person: UserSummary | null }) {
  const { t } = useI18n();
  if (!person) return <span className="muted">{t('common.deletedAccount')}</span>;
  return (
    <span className="person">
      <strong>{person.display_name}</strong>
      <span>@{person.handle}</span>
    </span>
  );
}

const ACCOUNT_TONE: Record<AccountStatus, Tone> = {
  active: 'success',
  suspended: 'warning',
  deactivated: 'danger',
  pending_deletion: 'info',
  deleted: 'neutral',
};

export function AccountStatusBadge({ status }: { status: AccountStatus }) {
  const { t } = useI18n();
  return <Badge tone={ACCOUNT_TONE[status]}>{t(`accountStatus.${status}`)}</Badge>;
}

const REPORT_TONE: Record<ReportStatus, Tone> = {
  open: 'warning',
  in_review: 'info',
  actioned: 'success',
  dismissed: 'neutral',
};

export function ReportStatusBadge({ status }: { status: ReportStatus }) {
  const { t } = useI18n();
  return <Badge tone={REPORT_TONE[status]}>{t(`reportStatus.${status}`)}</Badge>;
}

const TX_TONE: Record<TransactionStatus, Tone> = {
  pending: 'info',
  succeeded: 'success',
  failed: 'danger',
  open: 'warning',
  won: 'success',
  lost: 'danger',
};

export function TransactionStatusBadge({ status }: { status: TransactionStatus }) {
  const { t } = useI18n();
  return <Badge tone={TX_TONE[status]}>{t(`txStatus.${status}`)}</Badge>;
}

export function PriorityBadge({ priority }: { priority: number }) {
  const tone: Tone = priority >= 80 ? 'danger' : priority >= 50 ? 'warning' : 'neutral';
  return <Badge tone={tone}>P{priority}</Badge>;
}

/** A modal built on <dialog> (focus trapping and Escape come from the browser). */
export function Dialog({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else dialog.setAttribute('open', '');
    }
    if (!open && dialog.open) {
      if (typeof dialog.close === 'function') dialog.close();
      else dialog.removeAttribute('open');
    }
  }, [open]);
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      {open && (
        <div className="dialog-body">
          <h2 id={titleId}>{title}</h2>
          {children}
        </div>
      )}
    </dialog>
  );
}
