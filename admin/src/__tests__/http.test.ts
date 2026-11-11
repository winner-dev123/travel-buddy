import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiError, buildUrl, requestJson } from '../api/http';
import { readConfig } from '../config';
import { en } from '../i18n/en';
import { pt } from '../i18n/pt';

afterEach(() => vi.unstubAllGlobals());

describe('API calls', () => {
  it('builds URLs without empty parameters', () => {
    expect(buildUrl('https://api.test', '/v1/admin/users', { q: 'ana', status: '', cursor: undefined, staff: true })).toBe(
      'https://api.test/v1/admin/users?q=ana&staff=true',
    );
  });

  it('turns problems into ApiError with the request ID and field errors', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              status: 422,
              code: 'validation_failed',
              detail: 'Check the fields.',
              request_id: 'req-1',
              errors: [{ field: 'notes', code: 'too_short', message: 'Too short' }],
            }),
            { status: 422, headers: { 'Content-Type': 'application/problem+json' } },
          ),
      ),
    );
    const error = (await requestJson('https://api.test/x').catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.code).toBe('validation_failed');
    expect(error.requestId).toBe('req-1');
    expect(error.fieldErrors).toEqual([{ field: 'notes', message: 'Too short' }]);
  });

  it('sends JSON without cookies or referrer', async () => {
    const fetchMock = vi.fn(async () => new Response('{"ok":true}', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    await requestJson('https://api.test/x', { method: 'POST', body: { a: 1 } });
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init).toMatchObject({ method: 'POST', credentials: 'omit', referrerPolicy: 'no-referrer', body: '{"a":1}' });
  });

  it('reports an unreachable server as network_error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('Failed to fetch'))));
    await expect(requestJson('https://api.test/x')).rejects.toMatchObject({ code: 'network_error', status: 0 });
  });
});

describe('configuration', () => {
  it('needs an https API URL and the Firebase key', () => {
    expect(() => readConfig({})).toThrow(/VITE_API_BASE_URL/);
    expect(() => readConfig({ VITE_API_BASE_URL: 'http://api.test', VITE_FIREBASE_API_KEY: 'k' })).toThrow(/https/);
    expect(readConfig({ VITE_API_BASE_URL: 'https://api.test/', VITE_FIREBASE_API_KEY: 'k' })).toEqual({
      apiBaseUrl: 'https://api.test',
      firebaseApiKey: 'k',
      environmentLabel: 'staging',
    });
    expect(readConfig({ VITE_API_BASE_URL: 'http://127.0.0.1:8000', VITE_FIREBASE_API_KEY: 'k' }).apiBaseUrl).toBe(
      'http://127.0.0.1:8000',
    );
  });
});

describe('translations', () => {
  it('has every English text in Portuguese, none empty, with the same placeholders', () => {
    for (const [key, text] of Object.entries(en)) {
      const translated = pt[key as keyof typeof en];
      expect(translated, key).toBeTruthy();
      const placeholders = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
      expect(placeholders(translated), key).toEqual(placeholders(text));
    }
  });
});
