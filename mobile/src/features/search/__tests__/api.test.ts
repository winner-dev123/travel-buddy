// req: DEST-008
import type { DestinationSummary } from '@/features/feed/types';

import { suggestionKey, whereIs, type Suggestion } from '../api';

const rio = {
  id: 'd-rio',
  kind: 'city',
  slug: 'rio-de-janeiro-br',
  path: 'brazil/rio-de-janeiro',
  name: 'Rio de Janeiro',
  country_code: 'BR',
  country_name: 'Brazil',
  region_name: 'Rio de Janeiro',
} as DestinationSummary;
const cristo: Suggestion = {
  type: 'place',
  destination: rio,
  place: {
    id: 'p1',
    name: 'Christ the Redeemer',
    category: 'attraction',
    destination_id: 'd-rio',
    location: { lat: -22.95, lng: -43.21 },
  },
};

it('says where a place or a town is, naming each part once', () => {
  expect(whereIs(cristo)).toBe('Rio de Janeiro, Brazil');
  expect(whereIs({ type: 'destination', destination: rio })).toBe('Rio de Janeiro, Brazil');
  expect(
    whereIs({
      type: 'destination',
      destination: { ...rio, name: 'Campinas', region_name: 'São Paulo' },
    }),
  ).toBe('São Paulo, Brazil');
  expect(
    whereIs({
      type: 'destination',
      destination: { ...rio, kind: 'country', region_name: null, country_name: null },
    }),
  ).toBe('');
});

it('keys places and destinations apart', () => {
  expect(suggestionKey(cristo)).toBe('place:p1');
  expect(suggestionKey({ type: 'destination', destination: rio })).toBe('destination:d-rio');
});
