import path from 'node:path';
import { fileURLToPath } from 'node:url';
import type { NextConfig } from 'next';
import createNextIntlPlugin from 'next-intl/plugin';

const here = path.dirname(fileURLToPath(import.meta.url));
const withNextIntl = createNextIntlPlugin('./src/i18n/request.ts');
const isProd = process.env.APP_ENV === 'production' || process.env.APP_ENV === 'staging';

/** Headers for every response. The CSP is set per request in src/proxy.ts. */
const securityHeaders = [
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'Cross-Origin-Opener-Policy', value: 'same-origin' },
  { key: 'Permissions-Policy', value: 'camera=(), microphone=(), payment=(), usb=(), geolocation=(self)' },
  ...(isProd ? [{ key: 'Strict-Transport-Security', value: 'max-age=63072000; includeSubDomains; preload' }] : []),
];

const mediaHost = process.env.NEXT_PUBLIC_MEDIA_HOST;

const nextConfig: NextConfig = {
  output: 'standalone',
  outputFileTracingRoot: path.join(here, '../..'),
  reactStrictMode: true,
  poweredByHeader: false,
  transpilePackages: [
    '@travelbuddy/ui',
    '@travelbuddy/api-client',
    '@travelbuddy/domain-types',
    '@travelbuddy/validation',
    '@travelbuddy/i18n',
  ],
  images: {
    formats: ['image/avif', 'image/webp'],
    remotePatterns: mediaHost ? [{ protocol: 'https', hostname: mediaHost }] : [],
  },
  experimental: {
    optimizePackageImports: ['lucide-react'],
  },
  async headers() {
    return [
      { source: '/:path*', headers: securityHeaders },
      { source: '/api/:path*', headers: [{ key: 'X-Robots-Tag', value: 'noindex, nofollow' }] },
    ];
  },
};

export default withNextIntl(nextConfig);
