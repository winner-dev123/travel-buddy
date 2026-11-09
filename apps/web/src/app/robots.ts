import type { MetadataRoute } from 'next';
import { env } from '@/server/env';

/** Private areas are disallowed AND carry noindex headers (crawlers may still learn URLs). */
const PRIVATE = ['/api/', '/admin', '/feed', '/posts', '/explore', '/saved', '/assistant', '/trips', '/companions', '/messages', '/groups', '/tours', '/profile', '/notifications', '/membership', '/settings', '/onboarding', '/login', '/register', '/dev/'];
const PREFIXES = ['', '/es', '/pt-br', '/fr', '/de'];

export default function robots(): MetadataRoute.Robots {
  const e = env();
  if (e.appEnv !== 'production') {
    return { rules: [{ userAgent: '*', disallow: '/' }] };
  }
  return {
    rules: [{ userAgent: '*', allow: '/', disallow: PREFIXES.flatMap((p) => PRIVATE.map((path) => `${p}${path}`)) }],
    sitemap: `${e.siteUrl}/sitemap.xml`,
    host: e.siteUrl,
  };
}
