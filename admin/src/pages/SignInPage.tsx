import QRCode from 'qrcode';
import { useEffect, useRef, useState, type FormEvent } from 'react';

import { ApiError } from '../api/http';
import {
  finishSecondFactor,
  finishTotpEnrollment,
  IdentityError,
  otpauthUri,
  signInWithPassword,
  startTotpEnrollment,
  type TotpEnrollment,
} from '../auth/identityToolkit';
import { useSession, type SignedOutNotice } from '../auth/session';
import { Button, ErrorNotice, Field } from '../components/ui';
import type { MessageKey } from '../i18n/en';
import { useI18n } from '../i18n/I18n';

type Step =
  | { kind: 'credentials' }
  | { kind: 'code'; pendingCredential: string; enrollmentId: string; justEnrolled: boolean }
  | { kind: 'enroll'; idToken: string; enrollment: TotpEnrollment };

const IDENTITY_MESSAGES = new Set([
  'INVALID_LOGIN_CREDENTIALS',
  'INVALID_PASSWORD',
  'EMAIL_NOT_FOUND',
  'TOO_MANY_ATTEMPTS_TRY_LATER',
  'USER_DISABLED',
  'INVALID_MFA_PENDING_CREDENTIAL',
  'UNVERIFIED_EMAIL',
  'NETWORK_ERROR',
  'TOTP_NOT_ENROLLED',
]);

function identityKey(code: string): MessageKey | null {
  if (IDENTITY_MESSAGES.has(code)) return `signin.error.${code}` as MessageKey;
  if (code.includes('VERIFICATION_CODE') || code === 'INVALID_CODE') return 'signin.error.INVALID_CODE';
  if (code === 'OPERATION_NOT_ALLOWED' || code.includes('MFA_NOT_ENABLED') || code.includes('TOTP')) {
    return 'signin.error.MFA_DISABLED';
  }
  return null;
}

export function SignInPage({ notice }: { notice?: SignedOutNotice }) {
  const { t } = useI18n();
  const { config, signIn, isStaff } = useSession();
  const [step, setStep] = useState<Step>({ kind: 'credentials' });
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [apiError, setApiError] = useState<unknown>(null);
  const [staffNotice, setStaffNotice] = useState<SignedOutNotice | undefined>(notice);
  // The password is only kept to sign in again right after the authenticator is set up.
  const passwordForEnrollment = useRef<string | null>(null);

  const apiKey = config.firebaseApiKey;

  const fail = (caught: unknown) => {
    setApiError(null);
    if (caught instanceof IdentityError) {
      const key = identityKey(caught.code);
      setError(key ? t(key) : t('signin.error.generic', { code: caught.code }));
    } else if (caught instanceof ApiError) {
      setError(null);
      setApiError(caught);
    } else {
      setError(t('errors.generic'));
    }
  };

  const reset = () => {
    passwordForEnrollment.current = null;
    setPassword('');
    setCode('');
    setError(null);
    setApiError(null);
    setStep({ kind: 'credentials' });
  };

  const finish = async (idToken: string) => {
    const outcome = await signIn(idToken);
    passwordForEnrollment.current = null;
    if (outcome === 'no_staff_access') {
      setStaffNotice('no_staff_access');
      reset();
    }
  };

  const submitCredentials = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setApiError(null);
    setStaffNotice(undefined);
    try {
      const result = await signInWithPassword(apiKey, email.trim(), password);
      if (result.kind === 'second_factor') {
        setPassword('');
        setStep({
          kind: 'code',
          pendingCredential: result.pendingCredential,
          enrollmentId: result.enrollmentId,
          justEnrolled: false,
        });
        return;
      }
      // No second factor yet: only staff accounts may set one up here.
      if (!(await isStaff(result.idToken))) {
        setStaffNotice('no_staff_access');
        reset();
        return;
      }
      passwordForEnrollment.current = password;
      setPassword('');
      const enrollment = await startTotpEnrollment(apiKey, result.idToken);
      setStep({ kind: 'enroll', idToken: result.idToken, enrollment });
    } catch (caught) {
      fail(caught);
    } finally {
      setBusy(false);
    }
  };

  const submitCode = async (event: FormEvent) => {
    event.preventDefault();
    if (step.kind !== 'code') return;
    setBusy(true);
    setError(null);
    setApiError(null);
    try {
      const idToken = await finishSecondFactor(apiKey, step.pendingCredential, step.enrollmentId, code.trim());
      await finish(idToken);
    } catch (caught) {
      fail(caught);
      setCode('');
    } finally {
      setBusy(false);
    }
  };

  const submitEnrollment = async (event: FormEvent) => {
    event.preventDefault();
    if (step.kind !== 'enroll') return;
    setBusy(true);
    setError(null);
    try {
      await finishTotpEnrollment(apiKey, step.idToken, step.enrollment.sessionInfo, code.trim());
      setCode('');
      const again = await signInWithPassword(apiKey, email.trim(), passwordForEnrollment.current ?? '');
      passwordForEnrollment.current = null;
      if (again.kind === 'second_factor') {
        setStep({
          kind: 'code',
          pendingCredential: again.pendingCredential,
          enrollmentId: again.enrollmentId,
          justEnrolled: true,
        });
      } else {
        reset();
      }
    } catch (caught) {
      fail(caught);
      setCode('');
    } finally {
      setBusy(false);
    }
  };

  // Draw the QR code locally (the secret never leaves the browser except to Firebase).
  const enrollment = step.kind === 'enroll' ? step.enrollment : null;
  const [qrImage, setQrImage] = useState<{ secret: string; url: string } | null>(null);
  useEffect(() => {
    if (!enrollment) return;
    let cancelled = false;
    QRCode.toDataURL(otpauthUri(email.trim(), enrollment), { margin: 0, width: 176 })
      .then((url) => {
        if (!cancelled) setQrImage({ secret: enrollment.sharedSecretKey, url });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [enrollment, email]);
  const qr = enrollment && qrImage?.secret === enrollment.sharedSecretKey ? qrImage.url : null;

  const codeField = (
    <Field label={t('signin.code')}>
      {(props) => (
        <input
          {...props}
          className="code-input"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="[0-9]{6}"
          maxLength={6}
          required
          autoFocus
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
        />
      )}
    </Field>
  );

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <div className="stack">
          <span className="brand-name">
            Travel <span>Buddy</span>
          </span>
          <span className="overline">
            {t('app.console')} · {config.environmentLabel}
          </span>
        </div>

        {staffNotice && (
          <div className={`notice ${staffNotice === 'no_staff_access' ? 'warning' : ''}`} role="status">
            {t(`signin.notice.${staffNotice}`)}
          </div>
        )}
        {error && (
          <div className="notice danger" role="alert">
            {error}
          </div>
        )}
        {apiError !== null && <ErrorNotice error={apiError} />}

        {step.kind === 'credentials' && (
          <form className="stack" onSubmit={submitCredentials}>
            <h1>{t('signin.title')}</h1>
            <p className="muted">{t('signin.subtitle')}</p>
            <Field label={t('signin.email')}>
              {(props) => (
                <input
                  {...props}
                  type="email"
                  autoComplete="username"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              )}
            </Field>
            <Field label={t('signin.password')}>
              {(props) => (
                <input
                  {...props}
                  type="password"
                  autoComplete="current-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              )}
            </Field>
            <Button type="submit" variant="primary" disabled={busy}>
              {busy ? t('common.loading') : t('signin.submit')}
            </Button>
          </form>
        )}

        {step.kind === 'code' && (
          <form className="stack" onSubmit={submitCode}>
            <h1>{t('signin.codeTitle')}</h1>
            {step.justEnrolled && (
              <div className="notice success" role="status">
                {t('signin.enrolled')}
              </div>
            )}
            <p className="muted">{t('signin.codeHelp')}</p>
            {codeField}
            <Button type="submit" variant="primary" disabled={busy || code.length !== 6}>
              {busy ? t('common.loading') : t('signin.verify')}
            </Button>
            <Button variant="quiet" onClick={reset}>
              {t('signin.otherAccount')}
            </Button>
          </form>
        )}

        {step.kind === 'enroll' && (
          <form className="stack" onSubmit={submitEnrollment}>
            <h1>{t('signin.enrollTitle')}</h1>
            <p className="muted">{t('signin.enrollHelp')}</p>
            {qr && <img className="qr" src={qr} alt="" />}
            <div className="stack" style={{ gap: 4 }}>
              <span className="muted">{t('signin.enrollKey')}</span>
              <span className="mono">{step.enrollment.sharedSecretKey.replace(/(.{4})/g, '$1 ').trim()}</span>
            </div>
            {codeField}
            <Button type="submit" variant="primary" disabled={busy || code.length !== 6}>
              {busy ? t('common.loading') : t('signin.enrollSubmit')}
            </Button>
            <Button variant="quiet" onClick={reset}>
              {t('signin.otherAccount')}
            </Button>
          </form>
        )}
      </div>
    </div>
  );
}
