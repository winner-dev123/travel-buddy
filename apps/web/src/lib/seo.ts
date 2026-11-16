import type { Metadata } from 'next';
import { LOCALES, localeInfo, type LocaleCode } from '@travelbuddy/i18n';
import { absoluteUrl } from './paths';

/**
 * Canonical + hreflang alternates for a public path (docs/web/07). Every locale variant points at
 * the same canonical structure; `x-default` is the unprefixed English URL.
 */
export function alternatesFor(siteUrl: string, locale: LocaleCode, path: string): Metadata['alternates'] {
  const languages: Record<string, string> = {};
  for (const l of LOCALES) languages[l.bcp47] = absoluteUrl(siteUrl, l.code, path);
  languages['x-default'] = absoluteUrl(siteUrl, 'en', path);
  return { canonical: absoluteUrl(siteUrl, locale, path), languages };
}

export function publicPageMetadata(options: {
  siteUrl: string;
  locale: LocaleCode;
  path: string;
  title: string;
  description: string;
  type?: 'website' | 'article';
}): Metadata {
  const url = absoluteUrl(options.siteUrl, options.locale, options.path);
  return {
    title: options.title,
    description: options.description,
    alternates: alternatesFor(options.siteUrl, options.locale, options.path),
    openGraph: {
      title: options.title,
      description: options.description,
      url,
      type: options.type ?? 'website',
      locale: localeInfo(options.locale).bcp47.replace('-', '_'),
    },
    twitter: { card: 'summary_large_image', title: options.title, description: options.description },
  };
}

/**
 * Destinations outside the editorial directory (gazetteer towns, ADR-0035) still render for people
 * who reach them, but stay out of search results; links on them are still followed.
 */
export function destinationRobots(destination: { listed: boolean }): Pick<Metadata, 'robots'> {
  return destination.listed ? {} : { robots: { index: false, follow: true } };
}

/** For authenticated/private areas: never indexed, never followed (brief §26). */
export const PRIVATE_METADATA: Metadata = { robots: { index: false, follow: false, nocache: true } };
