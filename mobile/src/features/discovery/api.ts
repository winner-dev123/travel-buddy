import { ApiProblem, type ApiClient } from '@/api';
import type { DestinationDetail } from '@/features/explore/api';
import type { DeviceFix } from '@/features/feed/location';
import type { DestinationSummary, UserSummary } from '@/features/feed/types';

/** Version of the traveler-discovery consent text the user agrees to (DISC-001). */
export const DISCOVERY_CONSENT_VERSION = '2026-11-01';

export const discoveryKeys = {
  session: ['discovery', 'session'] as const,
  /** Not under 'discovery': refreshing the session doesn't need a new IP lookup. */
  approximate: ['approximate-location'] as const,
  travelers: (destinationId: string | undefined) =>
    ['discovery', 'travelers', destinationId] as const,
};

export interface DiscoverySession {
  id: string;
  destination: DestinationSummary;
  area: DestinationSummary | null;
  visibility: 'visible' | 'invisible';
  expires_at: string;
}

export interface TravelerCard {
  user: UserSummary;
  bio_snippet: string | null;
  presence: { destination: DestinationSummary; area: DestinationSummary | null };
  shared: { travel_styles: string[]; interests: string[]; languages: string[] };
  compatibility: 'high' | 'medium' | 'low';
  relationship: string;
  can_request_connection: boolean;
}

/** Records the consent, then turns discovery on with the chosen granularity. */
export async function enableDiscovery(
  client: ApiClient,
  granularity: 'city' | 'neighborhood',
): Promise<void> {
  await client.post('/v1/users/me/consents', {
    body: {
      consent_type: 'traveler_discovery',
      version: DISCOVERY_CONSENT_VERSION,
      granted: true,
      source: 'prompt',
    },
  });
  await client.patch('/v1/users/me/privacy', {
    body: { discovery_enabled: true, discovery_granularity: granularity },
  });
}

export async function disableDiscovery(client: ApiClient): Promise<void> {
  await client.patch('/v1/users/me/privacy', { body: { discovery_enabled: false } });
}

/** The active session, or null when none (404). */
export async function fetchSession(client: ApiClient): Promise<DiscoverySession | null> {
  try {
    return await client.get<DiscoverySession>('/v1/users/me/discovery-location');
  } catch (error) {
    if (error instanceof ApiProblem && error.status === 404) return null;
    throw error;
  }
}

export type ShareTarget =
  { mode: 'gps'; near: string; fix?: DeviceFix } | { mode: 'destination'; destinationId: string };

export function shareLocation(
  client: ApiClient,
  target: ShareTarget,
  visibility: 'visible' | 'invisible' = 'visible',
): Promise<DiscoverySession> {
  if (target.mode === 'gps') {
    const [lat, lng] = target.near.split(',').map(Number);
    const fix = target.fix;
    // When and how precisely the fix was taken: stale fixes are refused, coarse ones count
    // for the city only (LOC-007, LOC-008).
    const meta = fix
      ? {
          captured_at: fix.capturedAt,
          ...(fix.accuracyM !== null ? { accuracy_m: Math.round(fix.accuracyM) } : {}),
        }
      : {};
    return client.put<DiscoverySession>('/v1/users/me/discovery-location', {
      body: { mode: 'gps', point: { lat, lng, ...meta }, visibility },
    });
  }
  return client.put<DiscoverySession>('/v1/users/me/discovery-location', {
    body: { mode: 'destination', destination_id: target.destinationId, visibility },
  });
}

export function stopSharing(client: ApiClient): Promise<void> {
  return client.delete('/v1/users/me/discovery-location');
}

export async function discoverTravelers(client: ApiClient): Promise<TravelerCard[]> {
  const page = await client.get<{ data: TravelerCard[] }>('/v1/travelers/discover');
  return page.data;
}

/** Where the traveller seems to be, from their connection (LOC-010, ADR-0030). About a city. */
export interface ApproximateLocation {
  source: 'ip';
  precision: 'city' | 'country';
  /** For example "Helsinki, Finland". */
  label: string;
  center: { lat: number; lng: number };
  /** The covered city to search in, or null when discovery doesn't cover the area yet. */
  destination: DestinationDetail | null;
}

/** The approximate area, or null when the connection doesn't tell (422 `location_unresolvable`). */
export async function fetchApproximateLocation(
  client: ApiClient,
): Promise<ApproximateLocation | null> {
  try {
    return await client.get<ApproximateLocation>('/v1/users/me/approximate-location');
  } catch (error) {
    if (error instanceof ApiProblem && error.status === 422) return null;
    throw error;
  }
}
