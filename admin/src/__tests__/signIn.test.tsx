import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { SignInPage } from '../pages/SignInPage';
import { renderConsole } from '../test/render';

vi.mock('qrcode', () => ({ default: { toDataURL: vi.fn(async () => 'data:image/png;base64,QR') } }));

type Handler = (url: URL, body: Record<string, unknown>) => Response;

function stubIdentity(handler: Handler) {
  const fetchMock = vi.fn(async (input: string | URL, init: RequestInit = {}) =>
    handler(new URL(String(input)), JSON.parse(String(init.body ?? '{}')) as Record<string, unknown>),
  );
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

const ok = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
const fail = (message: string) => new Response(JSON.stringify({ error: { message } }), { status: 400 });

afterEach(() => vi.unstubAllGlobals());

async function enterCredentials() {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Email'), 'ana@example.com');
  await user.type(screen.getByLabelText('Password'), 'correct horse');
  await user.click(screen.getByRole('button', { name: 'Sign in' }));
  return user;
}

describe('staff sign-in', () => {
  it('signs in with password and authenticator code', async () => {
    stubIdentity((url, body) => {
      if (url.pathname.endsWith('accounts:signInWithPassword')) {
        return ok({ mfaPendingCredential: 'pending', mfaInfo: [{ mfaEnrollmentId: 'totp-1', totpInfo: {} }] });
      }
      if (url.pathname.endsWith('mfaSignIn:finalize')) {
        expect(body).toMatchObject({ totpVerificationInfo: { verificationCode: '123456' } });
        return ok({ idToken: 'id-with-mfa' });
      }
      return fail('UNKNOWN');
    });
    const { session } = renderConsole(<SignInPage />, { session: { state: { status: 'signed_out' } } });
    const user = await enterCredentials();
    expect(await screen.findByRole('heading', { name: 'Two-step sign-in' })).toBeInTheDocument();
    await user.type(screen.getByLabelText('Code'), '123456');
    await user.click(screen.getByRole('button', { name: 'Verify' }));
    await waitFor(() => expect(session.signIn).toHaveBeenCalledWith('id-with-mfa'));
  });

  it('shows a clear message for a wrong password', async () => {
    stubIdentity(() => fail('INVALID_LOGIN_CREDENTIALS'));
    renderConsole(<SignInPage />, { session: { state: { status: 'signed_out' } } });
    await enterCredentials();
    expect(await screen.findByRole('alert')).toHaveTextContent('Wrong email or password.');
  });

  it('sets up the authenticator for staff without one, then asks for a fresh code', async () => {
    let enrolled = false;
    const fetchMock = stubIdentity((url) => {
      if (url.pathname.endsWith('accounts:signInWithPassword')) {
        return enrolled
          ? ok({ mfaPendingCredential: 'pending-2', mfaInfo: [{ mfaEnrollmentId: 'totp-9', totpInfo: {} }] })
          : ok({ idToken: 'id-no-mfa' });
      }
      if (url.pathname.endsWith('mfaEnrollment:start')) {
        return ok({
          totpSessionInfo: {
            sharedSecretKey: 'ABCDEFGHIJKLMNOP',
            sessionInfo: 'enroll-session',
            verificationCodeLength: 6,
            periodSec: 30,
            hashingAlgorithm: 'SHA1',
          },
        });
      }
      if (url.pathname.endsWith('mfaEnrollment:finalize')) {
        enrolled = true;
        return ok({ idToken: 'ignored' });
      }
      return fail('UNKNOWN');
    });
    const { session } = renderConsole(<SignInPage />, { session: { state: { status: 'signed_out' } } });
    const user = await enterCredentials();
    expect(await screen.findByRole('heading', { name: 'Set up two-step sign-in' })).toBeInTheDocument();
    expect(session.isStaff).toHaveBeenCalledWith('id-no-mfa');
    expect(screen.getByText('ABCD EFGH IJKL MNOP')).toBeInTheDocument();
    await user.type(screen.getByLabelText('Code'), '654321');
    await user.click(screen.getByRole('button', { name: 'Turn on' }));
    expect(await screen.findByText(/Two-step sign-in is on/)).toBeInTheDocument();
    // The second password sign-in reused the remembered password, then forgot it.
    const passwordCalls = fetchMock.mock.calls.filter(([u]) => String(u).includes('signInWithPassword'));
    expect(passwordCalls).toHaveLength(2);
    expect(session.signIn).not.toHaveBeenCalled();
  });

  it('never sets up an authenticator for accounts without staff access', async () => {
    const fetchMock = stubIdentity((url) =>
      url.pathname.endsWith('accounts:signInWithPassword') ? ok({ idToken: 'id' }) : fail('UNKNOWN'),
    );
    renderConsole(<SignInPage />, {
      session: { state: { status: 'signed_out' }, isStaff: vi.fn(async () => false) },
    });
    await enterCredentials();
    expect(await screen.findByText(/This account has no staff access/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('mfaEnrollment'))).toBe(false);
  });
});
