import type { ApiClient } from '@/api';
import type { PlaceSummary } from '@/features/explore/api';
import { fixParams, type DeviceFix } from '@/features/feed/location';
import type { DestinationSummary, Page } from '@/features/feed/types';

/** Contract `Suggestion` (ADR-0035): a destination, or a tourist place with its destination. */
export type Suggestion =
  | { type: 'destination'; destination: DestinationSummary; place?: null }
  | { type: 'place'; destination: DestinationSummary; place: PlaceSummary };

export const searchKeys = {
  suggest: (q: string) => ['destinations', 'suggest', q] as const,
};

/** Search as you type: towns, neighbourhoods, countries and places to visit, never streets. */
export async function suggestDestinations(
  client: ApiClient,
  q: string,
  limit = 10,
): Promise<Suggestion[]> {
  const page = await client.get<Page<Suggestion>>('/v1/destinations/suggest', {
    query: { q, limit },
  });
  return page.data;
}

/** The destination a device position is in (LOC-005); the position is used once, never kept. */
export function resolveDestination(client: ApiClient, fix: DeviceFix): Promise<DestinationSummary> {
  return client.get<DestinationSummary>('/v1/destinations/resolve', {
    query: { near: fix.near, ...fixParams(fix) },
  });
}

/** Names joined once each: "Rio de Janeiro, Rio de Janeiro" (city and state) reads as one. */
function joinDistinct(parts: (string | null | undefined)[]): string {
  const out: string[] = [];
  for (const part of parts) {
    if (part && !out.some((seen) => seen.toLowerCase() === part.toLowerCase())) out.push(part);
  }
  return out.join(', ');
}

/** "São Paulo, Brazil" under Campinas: what tells a town or place apart from its namesakes. */
export function whereIs(suggestion: Suggestion): string {
  const { destination } = suggestion;
  if (suggestion.type === 'place') {
    return joinDistinct([destination.name, destination.region_name, destination.country_name]);
  }
  return joinDistinct([destination.region_name, destination.country_name]);
}

export function suggestionKey(suggestion: Suggestion): string {
  return suggestion.type === 'place'
    ? `place:${suggestion.place.id}`
    : `destination:${suggestion.destination.id}`;
}
