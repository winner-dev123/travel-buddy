import type { ApiClient } from '@/api';
import type { DestinationSummary } from '@/features/feed/types';

/** Contract `UpcomingDestination`. */
export interface UpcomingDestination {
  id: string;
  destination: DestinationSummary;
  start_date: string | null;
  end_date: string | null;
  share_for_discovery: boolean;
  created_at: string;
}

export const upcomingKey = ['me', 'upcoming-destinations'] as const;

export async function listUpcoming(client: ApiClient): Promise<UpcomingDestination[]> {
  return (await client.get<{ data: UpcomingDestination[] }>('/v1/users/me/upcoming-destinations'))
    .data;
}

/** Never shared for discovery from here: that stays an explicit opt-in (privacy by default). */
export function addUpcoming(
  client: ApiClient,
  body: { destination_id: string; start_date?: string; end_date?: string },
): Promise<UpcomingDestination> {
  return client.post<UpcomingDestination>('/v1/users/me/upcoming-destinations', { body });
}

export function removeUpcoming(client: ApiClient, selectionId: string): Promise<void> {
  return client.delete(`/v1/users/me/upcoming-destinations/${selectionId}`);
}
