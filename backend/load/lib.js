// Shared helpers for the k6 scenarios (BL-6.04). See README.md before running anything.
import http from 'k6/http';
import { check, fail } from 'k6';

export const BASE_URL = (__ENV.BASE_URL || 'http://localhost:8000').replace(/\/$/, '');

// Safety net: refuse to point load at production unless explicitly confirmed.
export function guard() {
  if (/travelbuddy\.app/.test(BASE_URL) && __ENV.I_HAVE_APPROVAL !== 'yes') {
    fail('Refusing to load-test a production host without I_HAVE_APPROVAL=yes.');
  }
}

/** One access token per virtual user: from TOKENS (comma-separated, pre-issued staging users)
 * or, on development/staging stacks with the dev IdP enabled, minted per VU. */
export function tokenFor(vu) {
  if (__ENV.TOKENS) {
    const tokens = __ENV.TOKENS.split(',').filter(Boolean);
    return tokens[(vu - 1) % tokens.length];
  }
  const sub = `load-${vu}-${__ENV.RUN_ID || 'local'}`;
  const minted = http.post(
    `${BASE_URL}/v1/dev/idp/token`,
    JSON.stringify({ sub, email: `${sub}@example.com`, email_verified: true }),
    { headers: { 'Content-Type': 'application/json' }, tags: { name: 'setup' } },
  );
  if (minted.status !== 200) fail(`dev IdP unavailable (${minted.status}); set TOKENS instead`);
  const idToken = minted.json('id_token');
  const body = JSON.stringify({ id_token: idToken, client: 'android' });
  const headers = { headers: { 'Content-Type': 'application/json' }, tags: { name: 'setup' } };
  let session = http.post(`${BASE_URL}/v1/auth/login`, body, headers);
  if (session.status === 404 || session.status === 401) {
    session = http.post(
      `${BASE_URL}/v1/auth/register`,
      JSON.stringify({
        id_token: idToken,
        client: 'android',
        birth_date: '1990-05-17',
        locale: 'en',
        // Must match the deployment's legal versions (GET /v1/client-config → legal).
        accepted_terms_version: __ENV.TERMS_VERSION || '2026-11-01',
        accepted_privacy_version: __ENV.PRIVACY_VERSION || '2026-11-01',
      }),
      headers,
    );
  }
  check(session, { 'signed in': (r) => r.status === 200 || r.status === 201 });
  return session.json('tokens.access_token');
}

export function authed(token, name) {
  return {
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    tags: { name },
  };
}

export function uuid() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}
