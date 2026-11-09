import type { MetadataRoute } from 'next';
import type { DestinationSummary, PublicPost } from '@travelbuddy/domain-types';
import { LOCALES } from '@travelbuddy/i18n';
import { absoluteUrl, destinationHref, storyHref } from '@/lib/paths';
import { env } from '@/server/env';
import { publicApi } from '@/server/platform';

export const revalidate = 3600;

const SITEMAP_CACHE = { revalidate: 3600, tags: ['sitemap'] };
const STATIC_PATHS = ['/', '/destinations', '/stories', '/pricing', '/download', '/about'];

function entry(siteUrl: string, path: string, lastModified?: string, priority?: number): MetadataRoute.Sitemap[number] {
  const languages: Record<string, string> = {};
  for (const l of LOCALES) languages[l.bcp47] = absoluteUrl(siteUrl, l.code, path);
  languages['x-default'] = absoluteUrl(siteUrl, 'en', path);
  return { url: absoluteUrl(siteUrl, 'en', path), lastModified, priority, alternates: { languages } };
}

/**
 * One URL entry per page with hreflang alternates for every locale (docs/web/07). Only public,
 * indexable content: destinations (stable `sort=slug` enumeration) and public stories.
 * Private areas, drafts and legal placeholders are excluded.
 */
export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const siteUrl = env().siteUrl;
  const api = await publicApi('en');
  const destinations: DestinationSummary[] = [];
  try {
    let cursor: string | null | undefined;
    for (let i = 0; i < 100; i++) {
      const page = await api.destinations.list({ kind: ['country', 'city'], sort: 'slug', limit: 100, cursor }, SITEMAP_CACHE);
      destinations.push(...page.data);
      if (!page.page.has_more || !page.page.next_cursor) break;
      cursor = page.page.next_cursor;
    }
  } catch {
    // Platform unavailable: publish the static part; the next revalidation fills it in.
  }
  let stories: PublicPost[] = [];
  try {
    // PROF-008: only stories whose authors opted into search-engine indexing.
    stories = (await api.publicPosts.list({ limit: 100 }, SITEMAP_CACHE)).data.filter((s) => s.indexable === true);
  } catch {
    stories = [];
  }

  return [
    ...STATIC_PATHS.map((p) => entry(siteUrl, p, undefined, p === '/' ? 1 : 0.7)),
    ...destinations.map((d) => entry(siteUrl, destinationHref(d.path), undefined, d.kind === 'city' ? 0.8 : 0.6)),
    ...stories.map((s) => entry(siteUrl, storyHref(s.id), s.edited_at ?? s.published_at, 0.5)),
  ];
}
