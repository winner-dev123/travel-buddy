/**
 * Formerly web-proposed contract extensions. All five requests from 2026-11-09 were accepted into
 * contracts/openapi/openapi.yaml (destinations list, DestinationSummary card fields, anonymous free
 * guides, FAQ sections, media attribution), so these are now plain aliases of generated types.
 */
import type { components } from './generated';
import type { CountryCode, CursorQuery, DestinationKind } from './contract';

type S = components['schemas'];

export type Continent = S['Continent'];
export const CONTINENTS = [
  'africa',
  'asia',
  'europe',
  'middle_east',
  'north_america',
  'central_america_caribbean',
  'south_america',
  'oceania',
] as const satisfies readonly Continent[];

export type DestinationSummary = S['DestinationSummary'];
export type Destination = S['Destination'];
export type Guide = S['Guide'];
export type GuideSection = Guide['sections'][number];
export type GuideFaqItem = NonNullable<GuideSection['faq_items']>[number];
export type MediaAttribution = NonNullable<S['MediaRef']['attribution']>;

/** Query for `GET /v1/destinations` (operationId listDestinations). Use `sort: 'slug'` for sitemaps. */
export interface DestinationListQuery extends CursorQuery {
  kind?: DestinationKind[];
  country?: CountryCode;
  continent?: Continent;
  featured?: boolean;
  sort?: 'popularity' | 'slug';
}
