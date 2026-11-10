import type { ApiClient } from '@/api';
import { fixParams, type DeviceFix } from '@/features/feed/location';
import type { DestinationSummary, Page, UserSummary } from '@/features/feed/types';

export type PlaceCategory =
  | 'attraction'
  | 'restaurant'
  | 'cafe'
  | 'bar'
  | 'museum'
  | 'beach'
  | 'trail'
  | 'viewpoint'
  | 'park'
  | 'market'
  | 'lodging'
  | 'transit_hub'
  | 'other';

/** Contract `PlaceSummary`. */
export interface PlaceSummary {
  id: string;
  name: string;
  category: PlaceCategory;
  destination_id: string;
  location: { lat: number; lng: number };
}

/** Contract `Place`: licensed provider data, always shown with its freshness (DEST-003). */
export interface Place extends PlaceSummary {
  address: Record<string, string> | null;
  attributes: Record<string, unknown>;
  data_freshness_at: string;
  data_stale?: boolean;
  attribution: { provider: string; license: string; text: string; url: string | null };
  status: 'active' | 'closed_permanently';
}

export interface SavedPlace {
  place: PlaceSummary;
  collection: string;
  note: string | null;
  created_at: string;
}

export interface DestinationDetail extends DestinationSummary {
  centroid: { lat: number; lng: number };
  time_zone: string;
}

export interface SourceAttribution {
  kind: 'catalog_place' | 'destination_guide' | 'licensed_provider' | 'ai_general_knowledge';
  provider?: string | null;
  license?: string | null;
}

export interface ProposedActivity {
  kind: 'activity' | 'meal' | 'transit' | 'lodging' | 'note' | 'free_time';
  title: string;
  description: string;
  place_id: string | null;
  unverified: boolean;
  suggested_start_time: string | null;
  estimated_duration_minutes: number;
  confidence: number;
  rationale: string;
  place: PlaceSummary | null;
  source_attribution: SourceAttribution[];
}

export interface ItineraryProposal {
  itinerary: {
    destination: DestinationSummary;
    start_date: string;
    end_date: string;
    time_zone: string;
    days: {
      day_index: number;
      date: string;
      theme: string | null;
      items: ProposedActivity[];
    }[];
    sources: SourceAttribution[];
  };
  warnings: string[];
  disclaimer: string;
  confidence: number;
}

/** Contract `AIGeneration`. */
export interface AIGeneration {
  id: string;
  feature: 'itinerary_generate' | 'trip_replan';
  status: 'pending' | 'succeeded' | 'failed';
  created_at: string;
  completed_at: string | null;
  result: ItineraryProposal | null;
  error: { code: string; detail?: string } | null;
  quota: { limit: number; used: number; resets_at: string | null };
}

export interface GenerateItinerary {
  destination_id: string;
  start_date: string;
  end_date: string;
  interests?: string[];
  pace?: 'relaxed' | 'moderate' | 'packed';
  preferences?: string;
}

export interface TripItem {
  id: string;
  kind: ProposedActivity['kind'];
  title: string;
  notes: string | null;
  start_time: string | null;
  duration_minutes: number | null;
  origin: 'user' | 'ai';
  unverified: boolean;
  place: PlaceSummary | null;
}

/** Contract `Trip` (the fields the app uses). */
export interface Trip {
  id: string;
  title: string;
  start_date: string;
  end_date: string;
  status: 'planning' | 'active' | 'completed' | 'archived';
  origin: 'manual' | 'ai_generated' | 'ai_assisted';
  destinations: { destination: DestinationSummary }[];
  days: { id: string; day_index: number; date: string | null; items: TripItem[] }[];
  owner: UserSummary;
  visibility: TripVisibility;
  group_id: string | null;
  collaborators: { user: UserSummary; role: CollaboratorRole }[];
  version: number;
}

export type TripVisibility = 'private' | 'connections' | 'group' | 'public';
export type CollaboratorRole = 'editor' | 'viewer';

export interface TripSummary {
  id: string;
  title: string;
  start_date: string;
  end_date: string;
  status: Trip['status'];
  origin: Trip['origin'];
  destinations: DestinationSummary[];
  role: 'owner' | 'editor' | 'viewer';
}

export const exploreKeys = {
  destination: (id: string) => ['destinations', id] as const,
  nearby: (near: string) => ['places', 'nearby', near] as const,
  search: (destinationId: string, q: string) => ['places', 'search', destinationId, q] as const,
  place: (id: string) => ['places', id] as const,
  saved: ['places', 'saved'] as const,
  generation: (id: string) => ['ai', 'generations', id] as const,
  trips: ['trips'] as const,
  trip: (id: string) => ['trips', id] as const,
};

/** Editorially featured destinations (DEST-004), to start exploring without typing. */
export async function featuredDestinations(client: ApiClient): Promise<DestinationSummary[]> {
  return (
    await client.get<{ data: DestinationSummary[] }>('/v1/destinations/featured', {
      query: { limit: 12 },
    })
  ).data;
}

/** Neighbourhoods and districts of a city (LOC-002, localized per DEST-002). */
export async function destinationChildren(
  client: ApiClient,
  id: string,
): Promise<DestinationSummary[]> {
  return (
    await client.get<{ data: DestinationSummary[] }>(`/v1/destinations/${id}/children`, {
      query: { limit: 30 },
    })
  ).data;
}

export function getDestination(client: ApiClient, id: string): Promise<DestinationDetail> {
  return client.get<DestinationDetail>(`/v1/destinations/${id}`);
}

export async function nearbyPlaces(
  client: ApiClient,
  near: string,
  fix?: DeviceFix,
): Promise<PlaceSummary[]> {
  const page = await client.get<Page<PlaceSummary>>('/v1/places/nearby', {
    query: { near, radius_m: 5000, limit: 30, ...fixParams(fix) },
  });
  return page.data;
}

export async function searchPlaces(
  client: ApiClient,
  destinationId: string,
  q: string,
): Promise<PlaceSummary[]> {
  const page = await client.get<Page<PlaceSummary>>('/v1/places/search', {
    query: { q, destination_id: destinationId, limit: 20 },
  });
  return page.data;
}

export function getPlace(client: ApiClient, id: string): Promise<Place> {
  return client.get<Place>(`/v1/places/${id}`);
}

export async function listSavedPlaces(client: ApiClient): Promise<SavedPlace[]> {
  const page = await client.get<Page<SavedPlace>>('/v1/users/me/saved-places', {
    query: { limit: 100 },
  });
  return page.data;
}

export function savePlace(client: ApiClient, placeId: string): Promise<SavedPlace> {
  return client.put<SavedPlace>(`/v1/users/me/saved-places/${placeId}`, { body: {} });
}

export function unsavePlace(client: ApiClient, placeId: string): Promise<void> {
  return client.delete(`/v1/users/me/saved-places/${placeId}`);
}

export function generateItinerary(
  client: ApiClient,
  idempotencyKey: string,
  body: GenerateItinerary,
): Promise<AIGeneration> {
  return client.post<AIGeneration>('/v1/ai/itineraries/generate', { body, idempotencyKey });
}

export function getGeneration(client: ApiClient, id: string): Promise<AIGeneration> {
  return client.get<AIGeneration>(`/v1/ai/generations/${id}`);
}

export async function listTrips(client: ApiClient): Promise<TripSummary[]> {
  const page = await client.get<Page<TripSummary>>('/v1/trips', { query: { limit: 50 } });
  return page.data;
}

export function getTrip(client: ApiClient, id: string): Promise<Trip> {
  return client.get<Trip>(`/v1/trips/${id}`);
}

/** Save a proposal as a new trip: create it (a day per date), then copy the proposed days in. */
export async function saveProposalAsTrip(
  client: ApiClient,
  idempotencyKey: string,
  generation: AIGeneration,
  title: string,
): Promise<Trip> {
  const proposal = generation.result!;
  const trip = await client.post<Trip>('/v1/trips', {
    idempotencyKey,
    body: {
      title: title.slice(0, 100),
      start_date: proposal.itinerary.start_date,
      end_date: proposal.itinerary.end_date,
      destination_ids: [proposal.itinerary.destination.id],
    },
  });
  return client.post<Trip>(`/v1/trips/${trip.id}/apply-itinerary`, {
    body: { generation_id: generation.id, mode: 'replace' },
    ifMatchVersion: trip.version,
  });
}

export interface ReplanTrip {
  instruction: string;
  base_version: number;
  day_indexes?: number[];
}

export function setTripVisibility(
  client: ApiClient,
  tripId: string,
  version: number,
  visibility: TripVisibility,
): Promise<Trip> {
  return client.patch<Trip>(`/v1/trips/${tripId}`, {
    body: { visibility },
    ifMatchVersion: version,
  });
}

/** Share with a connection or a member of the trip's group, or change their role (TRIP-005). */
export function shareTrip(
  client: ApiClient,
  tripId: string,
  userId: string,
  role: CollaboratorRole,
): Promise<Trip> {
  return client.put<Trip>(`/v1/trips/${tripId}/collaborators/${userId}`, { body: { role } });
}

export function unshareTrip(client: ApiClient, tripId: string, userId: string): Promise<void> {
  return client.delete(`/v1/trips/${tripId}/collaborators/${userId}`);
}

export function replanTrip(
  client: ApiClient,
  idempotencyKey: string,
  tripId: string,
  body: ReplanTrip,
): Promise<AIGeneration> {
  return client.post<AIGeneration>(`/v1/ai/trips/${tripId}/replan`, { body, idempotencyKey });
}

/** Replace the proposal's days in an existing trip (the trip's current version is required). */
export async function applyProposalToTrip(
  client: ApiClient,
  tripId: string,
  generation: AIGeneration,
): Promise<Trip> {
  const trip = await getTrip(client, tripId);
  return client.post<Trip>(`/v1/trips/${tripId}/apply-itinerary`, {
    body: {
      generation_id: generation.id,
      mode: 'replace',
      day_indexes: generation.result!.itinerary.days.map((day) => day.day_index),
    },
    ifMatchVersion: trip.version,
  });
}

/** Contract `GuideSummary`. */
export interface GuideSummary {
  id: string;
  destination_id: string;
  locale: string;
  title: string;
  summary: string;
  tier: 'free' | 'premium' | 'purchasable';
  entitled: boolean;
  version: number;
}

export interface GuideSection {
  id: string;
  kind?: 'prose' | 'faq';
  heading: string;
  body_markdown: string;
  place_ids: string[];
  faq_items?: { question: string; answer_markdown: string }[];
}

/** Contract `Guide`. */
export interface Guide {
  id: string;
  destination: DestinationSummary;
  locale: string;
  title: string;
  summary: string;
  sections: GuideSection[];
  tier: GuideSummary['tier'];
  version: number;
  content_license: string;
  attribution: string | null;
}

export async function listGuides(
  client: ApiClient,
  destinationId: string,
): Promise<GuideSummary[]> {
  const result = await client.get<{ data: GuideSummary[] }>(
    `/v1/destinations/${destinationId}/guides`,
  );
  return result.data;
}

export function getGuide(client: ApiClient, id: string): Promise<Guide> {
  return client.get<Guide>(`/v1/guides/${id}`);
}
