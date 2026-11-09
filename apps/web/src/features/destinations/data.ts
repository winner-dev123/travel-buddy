import 'server-only';
import { cache } from 'react';
import { isApiError } from '@travelbuddy/api-client';
import type { Destination, Guide, PublicPost } from '@travelbuddy/domain-types';
import { publicApi } from '@/server/platform';

const CATALOG = { revalidate: 3600, tags: ['destinations'] };

export const getDestination = cache(async (locale: string, path: string): Promise<Destination | null> => {
  const api = await publicApi(locale);
  try {
    const slug = path.split('/').pop() ?? path;
    return await api.destinations.lookup(path, { ...CATALOG, tags: ['destinations', `destination:${slug}`] });
  } catch (error) {
    if (isApiError(error) && error.status === 404) return null;
    throw error;
  }
});

/** The destination's FREE editorial guide (anonymous per contract), if any. */
export const getFreeGuide = cache(async (locale: string, destinationId: string): Promise<Guide | null> => {
  const api = await publicApi(locale);
  try {
    const { data } = await api.destinations.guides(destinationId, CATALOG);
    const free = data.find((g) => g.tier === 'free');
    return free ? await api.guides.get(free.id, { ...CATALOG, tags: ['destinations', `guide:${free.id}`] }) : null;
  } catch (error) {
    if (isApiError(error) && (error.status === 401 || error.status === 403 || error.status === 404)) return null;
    throw error;
  }
});

export async function getDestinationStories(locale: string, destinationId: string, limit = 6): Promise<PublicPost[]> {
  const api = await publicApi(locale);
  const page = await api.publicPosts.list({ destination_id: destinationId, limit }, { revalidate: 60, tags: ['stories'] }).catch(() => null);
  return page?.data ?? [];
}

export async function getChildren(locale: string, destinationId: string) {
  const api = await publicApi(locale);
  const page = await api.destinations.children(destinationId, { limit: 50 }, CATALOG).catch(() => null);
  return page?.data ?? [];
}
