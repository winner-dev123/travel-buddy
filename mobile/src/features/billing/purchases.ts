import Constants from 'expo-constants';
import { Platform } from 'react-native';

import type { ApiClient } from '@/api';
import type { Entitlements } from '@/features/account/api';

/** An offer as the API lists it (`GET /v1/billing/products`; BILL-010). */
export interface Offer {
  id: string;
  sku: string;
  platform: 'ios' | 'android' | 'web';
  kind: 'auto_renewable' | 'non_renewing' | 'non_consumable';
  plan_key: 'premium' | null;
  period: string | null;
  title: string | null;
  description: string | null;
}

export const billingKeys = {
  offers: (platform: string) => ['billing', 'offers', platform] as const,
};

/** The store this app sells through. */
export function storePlatform(): 'ios' | 'android' {
  return Platform.OS === 'ios' ? 'ios' : 'android';
}

/** Premium offers in display order (content purchases are sold on their own screens). */
export async function fetchOffers(client: ApiClient): Promise<Offer[]> {
  const page = await client.get<{ data: Offer[] }>('/v1/billing/products', {
    query: { platform: storePlatform() },
  });
  return page.data.filter((offer) => offer.plan_key === 'premium');
}

/** Why the paywall opened: the gated feature or quota (docs/07 §3). */
export const PAYWALL_REASONS = [
  'groups.create',
  'challenges.create',
  'guides.premium',
  'offline.packages',
  'ai.trip_replan',
  'ai.itinerary_generations',
] as const;
export type PaywallReason = (typeof PAYWALL_REASONS)[number];

export function paywallReason(value: unknown): PaywallReason | null {
  return PAYWALL_REASONS.find((reason) => reason === value) ?? null;
}

function transactionId(): string {
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
}

/**
 * Buys an offer through the backend's development store (development builds and a development
 * backend only): the same verification endpoint the stores' receipts go to, so the grant, the
 * ledger and the history behave as they will with real purchases.
 */
export async function buyWithTestStore(
  client: ApiClient,
  offer: Offer,
  idempotencyKey: string,
): Promise<Entitlements> {
  const transaction = `dev:${offer.sku}:${transactionId()}`;
  const body =
    storePlatform() === 'ios'
      ? { provider: 'apple', signed_transaction: transaction }
      : {
          provider: 'google',
          product_sku: offer.sku,
          purchase_token: transaction,
          package_name: Constants.expoConfig?.android?.package ?? 'com.travelbuddy.app',
        };
  const result = await client.post<{ entitlements: Entitlements }>('/v1/billing/purchases/verify', {
    body,
    idempotencyKey,
  });
  return result.entitlements;
}
