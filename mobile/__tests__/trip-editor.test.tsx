// req: TRIP-001, TRIP-004
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ApiProblem } from '@/api';
import { useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';
import type { Trip, TripItem } from '@/features/explore/api';
import { applyEdits, newEdit, type PendingEdit } from '@/features/trips/editor';
import { i18n } from '@/i18n';

import TripScreen from '../app/trips/[id]';

const mockApi = {
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  delete: jest.fn(),
  newIdempotencyKey: jest.fn(() => 'key-1'),
};
let mockOnline = true;
let mockUuid = 0;

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('@/offline/connectivity', () => ({ useIsOnline: () => mockOnline }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn(), back: jest.fn() }),
  useLocalSearchParams: () => ({ id: 't1' }),
  Stack: { Screen: () => null },
}));
jest.mock('expo-crypto', () => ({
  randomUUID: () => `00000000-0000-4000-8000-${String((mockUuid += 1)).padStart(12, '0')}`,
}));
jest.mock('expo-file-system', () => {
  const files = new Map<string, string>();
  const join = (parts: unknown[]) =>
    parts
      .map((part) => (typeof part === 'string' ? part : (part as { uri: string }).uri))
      .join('/');
  class Directory {
    uri: string;
    constructor(...parts: unknown[]) {
      this.uri = join(parts);
    }
    create() {}
  }
  class File {
    uri: string;
    constructor(...parts: unknown[]) {
      this.uri = join(parts);
    }
    get exists() {
      return files.has(this.uri);
    }
    async write(text: string) {
      files.set(this.uri, text);
    }
    async text() {
      return files.get(this.uri) ?? '';
    }
    delete() {
      files.delete(this.uri);
    }
  }
  return { Directory, File, Paths: { document: { uri: 'doc' } }, mockFiles: files };
});

const fs = jest.requireMock<{ mockFiles: Map<string, string> }>('expo-file-system');
const EDITS = 'doc/trip-edits/t1.json';

function item(id: string, title: string, overrides: Partial<TripItem> = {}): TripItem {
  return {
    id,
    kind: 'activity',
    title,
    notes: null,
    start_time: null,
    duration_minutes: null,
    origin: 'user',
    unverified: false,
    place: null,
    ...overrides,
  };
}

const person = (id: string, name: string) => ({
  id,
  handle: name.toLowerCase(),
  display_name: name,
  avatar: null,
});

function trip(overrides: Partial<Trip> = {}): Trip {
  return {
    id: 't1',
    title: 'Lisbon weekend',
    start_date: '2026-12-04',
    end_date: '2026-12-05',
    status: 'planning',
    origin: 'manual',
    destinations: [],
    days: [
      {
        id: 'd1',
        day_index: 0,
        date: '2026-12-04',
        items: [item('i1', 'Breakfast'), item('i2', 'Museum')],
      },
      { id: 'd2', day_index: 1, date: '2026-12-05', items: [] },
    ],
    owner: person('owner', 'Owner'),
    visibility: 'private',
    group_id: null,
    collaborators: [{ user: person('bea', 'Bea'), role: 'viewer' }],
    version: 3,
    ...overrides,
  };
}

function me(id: string): Me {
  return {
    account: {
      id,
      email: 'me@example.com',
      email_verified: true,
      status: 'active',
      primary_locale: 'en',
    },
    profile: { id, handle: 'me', display_name: 'Me', bio: null, account_visibility: 'public' },
    preferences: { ui_locale: 'en', time_zone: 'UTC' },
    privacy: { discovery_enabled: false, search_engine_indexing: false },
    roles: [],
    onboarding_completed: true,
    entitlements: { plan: 'free', features: {} },
  };
}

async function renderTrip() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false, gcTime: Infinity },
    },
  });
  return await render(
    <SafeAreaProvider
      initialMetrics={{
        frame: { x: 0, y: 0, width: 390, height: 844 },
        insets: { top: 0, left: 0, right: 0, bottom: 0 },
      }}
    >
      <QueryClientProvider client={client}>
        <TripScreen />
      </QueryClientProvider>
    </SafeAreaProvider>,
  );
}

const titles = (t: Trip, day = 0) => t.days[day]!.items.map((i) => i.title);

beforeEach(async () => {
  mockApi.get.mockReset();
  mockApi.post.mockReset();
  fs.mockFiles.clear();
  mockOnline = true;
  mockUuid = 0;
  useSessionStore.getState().setSignedIn(me('owner'));
  mockApi.get.mockResolvedValue(trip());
  await i18n.changeLanguage('en');
});

describe('applying pending edits', () => {
  it('creates, edits, moves and deletes items the way the server orders them', () => {
    const base = trip();
    const edits: PendingEdit[] = [
      newEdit('create', 'n1', { kind: 'meal', title: 'Lunch' }, 'd1'),
      newEdit('update', 'i2', { title: 'Tile museum', start_time: '15:00' }),
      newEdit('update', 'i2', { after_item_id: null }), // to the top
    ];
    let view = applyEdits(base, edits);
    expect(titles(view)).toEqual(['Tile museum', 'Breakfast', 'Lunch']);
    expect(view.days[0]!.items[0]!.start_time).toBe('15:00');
    view = applyEdits(base, [
      ...edits,
      newEdit('update', 'i1', { day_id: 'd2' }), // to the end of another day
      newEdit('update', 'n1', { after_item_id: 'i2' }),
      newEdit('delete', 'i2', {}),
    ]);
    expect(titles(view)).toEqual(['Lunch']);
    expect(titles(view, 1)).toEqual(['Breakfast']);
    expect(titles(base)).toEqual(['Breakfast', 'Museum']); // the server copy is untouched
  });
});

describe('trip editor', () => {
  it('adds an item and sends it in a sync batch with the trip version', async () => {
    mockApi.post.mockResolvedValue({
      trip: trip({
        version: 4,
        days: [
          {
            id: 'd1',
            day_index: 0,
            date: '2026-12-04',
            items: [
              item('i1', 'Breakfast'),
              item('i2', 'Museum'),
              item('00000000-0000-4000-8000-000000000002', 'Tram 28', { start_time: '09:30' }),
            ],
          },
          { id: 'd2', day_index: 1, date: '2026-12-05', items: [] },
        ],
      }),
      applied_op_ids: ['00000000-0000-4000-8000-000000000001'],
      conflicts: [],
    });
    await renderTrip();
    await fireEvent.press(await screen.findByTestId('trip-add-item-0'));
    await fireEvent.changeText(screen.getByTestId('item-title'), 'Tram 28');
    await fireEvent.changeText(screen.getByTestId('item-time'), '9:30');
    expect(screen.getByTestId('item-time-error')).toBeTruthy(); // 24-hour HH:MM only
    expect(screen.getByTestId('item-save')).toBeDisabled();
    await fireEvent.changeText(screen.getByTestId('item-time'), '09:30');
    await fireEvent.press(screen.getByTestId('item-save'));

    await waitFor(() => expect(mockApi.post).toHaveBeenCalled());
    expect(mockApi.post).toHaveBeenCalledWith('/v1/trips/t1/sync', {
      body: {
        base_version: 3,
        operations: [
          {
            op_id: '00000000-0000-4000-8000-000000000001',
            entity: 'item',
            action: 'create',
            entity_id: '00000000-0000-4000-8000-000000000002',
            parent_id: 'd1',
            fields: { kind: 'activity', title: 'Tram 28', start_time: '09:30' },
            client_updated_at: expect.any(String),
          },
        ],
      },
      idempotencyKey: 'key-1',
    });
    expect(await screen.findByText('09:30 · Tram 28')).toBeTruthy();
    await waitFor(() => expect(fs.mockFiles.has(EDITS)).toBe(false)); // nothing left to send
  });

  it('keeps edits on the device while offline and shows them at once', async () => {
    mockOnline = false;
    await renderTrip();
    await fireEvent.press(await screen.findByTestId('trip-edit-item-i2'));
    await fireEvent.changeText(screen.getByTestId('item-title'), 'Tile museum');
    await fireEvent.press(screen.getByTestId('item-save'));

    expect(await screen.findByText('Tile museum')).toBeTruthy();
    expect(screen.getByTestId('trip-edit-offline')).toHaveTextContent(
      "You're offline. 1 change will be saved when you're back online.",
    );
    expect(mockApi.post).not.toHaveBeenCalled();
    await waitFor(() => expect(fs.mockFiles.has(EDITS)).toBe(true));
    const stored = JSON.parse(fs.mockFiles.get(EDITS)!) as PendingEdit[];
    expect(stored.map((e) => [e.action, e.entity_id, e.fields])).toEqual([
      ['update', 'i2', { title: 'Tile museum' }], // only what changed
    ]);
  });

  it('sends the edits kept from an earlier session and reports replaced ones', async () => {
    const kept = [newEdit('delete', 'i1', {}), newEdit('update', 'i2', { after_item_id: null })];
    fs.mockFiles.set(EDITS, JSON.stringify(kept));
    mockApi.post.mockResolvedValue({
      trip: trip({ version: 5 }),
      applied_op_ids: [kept[0]!.op_id],
      conflicts: [
        {
          op_id: kept[1]!.op_id,
          entity: 'item',
          entity_id: 'i2',
          reason: 'modified_on_server',
          server_state: {},
        },
      ],
    });
    await renderTrip();
    await waitFor(() => expect(mockApi.post).toHaveBeenCalled());
    const body = mockApi.post.mock.calls[0]![1].body;
    expect(body.operations.map((op: { action: string }) => op.action)).toEqual([
      'delete',
      'update',
    ]);
    expect(body.operations[1].fields).toEqual({ after_item_id: null });
    expect(await screen.findByTestId('trip-edit-conflicts')).toHaveTextContent(
      '1 of your changes was replaced by a newer edit from someone else.',
    );
    await waitFor(() => expect(fs.mockFiles.has(EDITS)).toBe(false));
  });

  it('moves an item up to the top of its day', async () => {
    mockApi.post.mockResolvedValue({
      trip: trip({ version: 4 }),
      applied_op_ids: [],
      conflicts: [],
    });
    await renderTrip();
    await fireEvent.press(await screen.findByTestId('trip-edit-item-i2'));
    expect(screen.getByTestId('item-move-down')).toBeDisabled(); // already last
    await fireEvent.press(screen.getByTestId('item-move-up'));
    await waitFor(() => expect(mockApi.post).toHaveBeenCalled());
    const [op] = mockApi.post.mock.calls[0]![1].body.operations;
    expect([op.action, op.entity_id, op.fields]).toEqual(['update', 'i2', { after_item_id: null }]);
  });

  it('offers to discard edits the server refuses, without retrying in a loop', async () => {
    mockApi.post.mockRejectedValue(
      new ApiProblem(
        { type: 'about:blank', title: 'Forbidden', status: 403, code: 'forbidden' },
        'r1',
      ),
    );
    await renderTrip();
    await fireEvent.press(await screen.findByTestId('trip-edit-item-i1'));
    await fireEvent.press(screen.getByTestId('item-delete'));
    expect(await screen.findByTestId('trip-edit-failed')).toBeTruthy();
    expect(mockApi.post).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('Breakfast')).toBeNull();
    await fireEvent.press(screen.getByTestId('trip-edit-discard'));
    expect(await screen.findByText('Breakfast')).toBeTruthy(); // back to the server's copy
    await waitFor(() => expect(fs.mockFiles.has(EDITS)).toBe(false));
    expect(mockApi.post).toHaveBeenCalledTimes(1);
  });

  it('shows no editing to viewers', async () => {
    useSessionStore.getState().setSignedIn(me('bea'));
    await renderTrip();
    expect(await screen.findByText('Breakfast')).toBeTruthy();
    expect(screen.queryByTestId('trip-add-item-0')).toBeNull();
    expect(screen.queryByTestId('trip-edit-item-i1')).toBeNull();
  });
});
