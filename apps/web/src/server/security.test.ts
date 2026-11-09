import { describe, expect, it } from 'vitest';
import { serializeJsonLd } from '@/components/json-ld';
import { parseEnv } from './env-core';
import { safeNextPath } from './safe-redirect';
import { needsRefresh, safeEqual, sealSession, unsealSession, type SessionData } from './session';

const SECRET = 'test-secret-that-is-at-least-thirty-two-characters';
const session: SessionData = {
  at: 'access-token',
  atExp: Date.now() + 15 * 60_000,
  rt: 'refresh-token',
  rtExp: Date.now() + 30 * 24 * 3600_000,
  uid: '0193a000-0000-7000-8000-000000000001',
  sid: '0193a000-0000-7000-8000-000000000002',
  roles: [],
};

describe('sealed session cookie (ADR-0011)', () => {
  it('round-trips and never exposes tokens in plaintext', async () => {
    const sealed = await sealSession(session, SECRET);
    expect(sealed).not.toContain('access-token');
    expect(sealed).not.toContain('refresh-token');
    expect(await unsealSession(sealed, SECRET)).toEqual(session);
  });

  it('rejects tampering and the wrong key', async () => {
    const sealed = await sealSession(session, SECRET);
    const tampered = `${sealed.slice(0, -4)}AAAA`;
    expect(await unsealSession(tampered, SECRET)).toBeNull();
    expect(await unsealSession(sealed, `${SECRET}-other`)).toBeNull();
    expect(await unsealSession('garbage', SECRET)).toBeNull();
    expect(await unsealSession(undefined, SECRET)).toBeNull();
  });

  it('refreshes ahead of expiry', () => {
    expect(needsRefresh({ ...session, atExp: Date.now() + 30_000 })).toBe(true);
    expect(needsRefresh(session)).toBe(false);
  });

  it('compares CSRF tokens in constant time semantics', () => {
    expect(safeEqual('abc', 'abc')).toBe(true);
    expect(safeEqual('abc', 'abd')).toBe(false);
    expect(safeEqual('abc', 'abcd')).toBe(false);
  });
});

describe('safeNextPath (open-redirect protection)', () => {
  it.each([
    ['/feed?tab=nearby', '/feed?tab=nearby'],
    ['/pt-br/feed', '/pt-br/feed'],
    ['https://evil.example/x', '/feed'],
    ['//evil.example', '/feed'],
    ['/\\evil.example', '/feed'],
    ['/feed\nSet-Cookie: x', '/feed'],
    ['javascript:alert(1)', '/feed'],
    ['/api/auth/logout', '/feed'],
    [null, '/feed'],
  ])('%s → %s', (input, expected) => {
    expect(safeNextPath(input)).toBe(expected);
  });
});

describe('JSON-LD serialization', () => {
  it('cannot break out of the script element', () => {
    const out = serializeJsonLd({ name: '</script><script>alert(1)</script>' });
    expect(out).not.toContain('</script>');
    expect(out).not.toContain('<');
    expect(JSON.parse(out)).toEqual({ name: '</script><script>alert(1)</script>' });
  });
});

describe('environment guards (docs/web/01 §7.1)', () => {
  it('defaults development to mock + dev identity', () => {
    const e = parseEnv({ APP_ENV: 'development' });
    expect(e.apiMode).toBe('mock');
    expect(e.identityProvider).toBe('dev');
  });

  it('refuses the mock adapter or dev identity outside development/test', () => {
    const base = {
      APP_ENV: 'production',
      API_BASE_URL: 'https://api.example.com',
      SESSION_SECRET: SECRET,
      OIDC_ISSUER: 'https://idp.example.com',
      OIDC_CLIENT_ID: 'web',
      OIDC_CLIENT_SECRET: 'secret',
      OIDC_REDIRECT_URI: 'https://www.example.com/api/auth/callback',
      NEXT_PUBLIC_MAP_STYLE_URL: 'https://tiles.example.com/style.json',
    };
    expect(() => parseEnv(base)).not.toThrow();
    expect(() => parseEnv({ ...base, TB_API_MODE: 'mock' })).toThrow(/mock is forbidden/);
    expect(() => parseEnv({ ...base, TB_IDENTITY_PROVIDER: 'dev' })).toThrow(/dev is forbidden/);
    expect(() => parseEnv({ ...base, SESSION_SECRET: 'short' })).toThrow(/SESSION_SECRET/);
    expect(() => parseEnv({ ...base, API_BASE_URL: undefined })).toThrow(/API_BASE_URL/);
  });
});
