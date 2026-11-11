import { useState, type FormEvent, type ReactNode } from 'react';
import { NavLink } from 'react-router';

import type { Permission } from '../api/types';
import { useSession } from '../auth/session';
import { KEYS, readItem, writeItem } from '../auth/storage';
import type { MessageKey } from '../i18n/en';
import { LOCALES, useI18n, type Locale } from '../i18n/I18n';
import { Badge, Button, Dialog, Field } from './ui';

export interface NavItem {
  to: string;
  label: MessageKey;
  permission: Permission;
}

/** Each page appears only for staff whose role has its permission (the API checks again). */
export const NAV: NavItem[] = [
  { to: '/', label: 'nav.overview', permission: 'users.read' },
  { to: '/reports', label: 'nav.reports', permission: 'moderation.reports.read' },
  { to: '/users', label: 'nav.users', permission: 'users.read' },
  { to: '/billing', label: 'nav.billing', permission: 'entitlements.grant' },
  { to: '/privacy', label: 'nav.privacy', permission: 'privacy.requests.manage' },
  { to: '/safety', label: 'nav.safety', permission: 'safety.filters.manage' },
  { to: '/audit', label: 'nav.audit', permission: 'audit.read' },
  { to: '/staff', label: 'nav.staff', permission: 'roles.assign' },
];

export const REASON_MIN = 10;
export const REASON_MAX = 500;

export function ReasonForm({ initial, onDone }: { initial?: string; onDone?: () => void }) {
  const { t } = useI18n();
  const { setReason } = useSession();
  const [value, setValue] = useState(initial ?? '');
  const trimmed = value.trim();
  const valid = trimmed.length >= REASON_MIN && trimmed.length <= REASON_MAX;
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!valid) return;
    setReason(trimmed);
    onDone?.();
  };
  return (
    <form className="stack" onSubmit={submit}>
      <p className="muted">{t('reason.help')}</p>
      <Field label={t('reason.label')} hint={t('reason.hint')}>
        {(props) => (
          <input
            {...props}
            value={value}
            maxLength={REASON_MAX}
            autoFocus
            onChange={(e) => setValue(e.target.value)}
          />
        )}
      </Field>
      <div className="dialog-actions">
        <Button type="submit" variant="primary" disabled={!valid}>
          {t('reason.submit')}
        </Button>
      </div>
    </form>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const { t, locale, setLocale } = useI18n();
  const { state, can, signOut, reason, config } = useSession();
  const [editingReason, setEditingReason] = useState(false);
  const [theme, setTheme] = useState<'dark' | 'light'>(() =>
    readItem('local', KEYS.theme) === 'light' ? 'light' : 'dark',
  );
  const chooseTheme = (next: 'dark' | 'light') => {
    setTheme(next);
    writeItem('local', KEYS.theme, next === 'light' ? 'light' : null);
    if (next === 'light') document.documentElement.dataset.theme = 'light';
    else delete document.documentElement.dataset.theme;
  };
  const me = state.status === 'signed_in' ? state.me : null;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-name">
            Travel <span>Buddy</span>
          </span>
          <span className="overline">{t('app.console')}</span>
        </div>
        <nav className="nav" aria-label={t('nav.main')}>
          {NAV.filter((item) => can(item.permission)).map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === '/'}>
              {t(item.label)}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          {me && (
            <div className="person">
              <strong>{me.profile.display_name}</strong>
              <span>
                @{me.profile.handle} · {me.roles.map((r) => t(`role.${r}`)).join(', ')}
              </span>
            </div>
          )}
          <div className="field">
            <label htmlFor="console-language">{t('nav.language')}</label>
            <select
              id="console-language"
              value={locale}
              onChange={(e) => setLocale(e.target.value as Locale)}
            >
              {LOCALES.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.label}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="console-theme">{t('nav.theme')}</label>
            <select
              id="console-theme"
              value={theme}
              onChange={(e) => chooseTheme(e.target.value as 'dark' | 'light')}
            >
              <option value="dark">{t('theme.dark')}</option>
              <option value="light">{t('theme.light')}</option>
            </select>
          </div>
          <Button onClick={() => void signOut()}>{t('nav.signOut')}</Button>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <Badge tone={config.environmentLabel === 'production' ? 'danger' : 'warning'}>
            <span className="env-badge">{config.environmentLabel}</span>
          </Badge>
          {reason && (
            <div className="row" style={{ minWidth: 0 }}>
              <span className="overline">{t('reason.current')}</span>
              <span
                style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '46vw' }}
                title={reason}
              >
                {reason}
              </span>
              <Button small variant="quiet" onClick={() => setEditingReason(true)}>
                {t('reason.change')}
              </Button>
            </div>
          )}
        </header>
        {/* Pages load data with the reason as the audit justification, so they wait for it. */}
        <main className="content">{reason ? children : null}</main>
      </div>
      <Dialog open={!reason || editingReason} title={t('reason.title')} onClose={() => reason && setEditingReason(false)}>
        <ReasonForm initial={reason ?? ''} onDone={() => setEditingReason(false)} />
      </Dialog>
    </div>
  );
}
