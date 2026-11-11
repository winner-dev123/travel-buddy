import { describe, expect, it } from 'vitest';

import { hostingConfig } from '../../scripts/deploy-hosting.mjs';

describe('hosting headers', () => {
  const config = hostingConfig('https://api.example.com');
  const all = config.headers.find((h) => h.glob === '**')!.headers;

  it('lets the page talk only to the API and Firebase Authentication', () => {
    const csp = all['Content-Security-Policy']!;
    expect(csp).toContain("connect-src 'self' https://api.example.com https://identitytoolkit.googleapis.com");
    expect(csp).toContain("script-src 'self'");
    expect(csp).not.toContain('unsafe-inline');
    expect(csp).not.toContain('unsafe-eval');
    expect(csp).toContain("frame-ancestors 'none'");
  });

  it('is never framed, sniffed or indexed, and leaks no referrer', () => {
    expect(all).toMatchObject({
      'X-Frame-Options': 'DENY',
      'X-Content-Type-Options': 'nosniff',
      'Referrer-Policy': 'no-referrer',
      'X-Robots-Tag': 'noindex, nofollow',
    });
    expect(all['Strict-Transport-Security']).toMatch(/max-age=\d{8}/);
  });

  it('serves the app for every path (client-side routes)', () => {
    expect(config.rewrites).toEqual([{ glob: '**', path: '/index.html' }]);
  });
});
