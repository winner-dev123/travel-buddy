// req: OFF-001, OFF-002, OFF-004, OFF-005
import { ed25519 } from '@noble/curves/ed25519';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import type { ReactElement } from 'react';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ApiNetworkError } from '@/api';
import { canonicalJson, verifyManifest, type OfflineManifest } from '@/features/offline/manifest';
import {
  downloadPackage,
  listDownloads,
  offlineGuide,
  OfflineIntegrityError,
  removeDownload,
  type OfflinePackageSummary,
} from '@/features/offline/store';
import { i18n } from '@/i18n';

import Downloads from '../app/downloads';
import GuideScreen from '../app/guides/[id]';

const mockApi = {
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  patch: jest.fn(),
  delete: jest.fn(),
  newIdempotencyKey: jest.fn(() => 'key-1'),
};
let mockParams: Record<string, string> = {};

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({
  useRouter: () => ({ push: jest.fn() }),
  useLocalSearchParams: () => mockParams,
  Stack: { Screen: () => null },
}));
jest.mock('@/auth/session', () => ({
  APP_VERSION: '0.1.0',
  clientPlatform: () => 'ios',
  getDeviceId: async () => 'device-0001-abcd',
}));
interface NodeCrypto {
  createHash(algorithm: string): {
    update(text: string, encoding: string): { digest(format: string): string };
  };
}
jest.mock('expo-crypto', () => ({
  CryptoDigestAlgorithm: { SHA256: 'SHA-256' },
  digestStringAsync: async (_algorithm: string, text: string) =>
    jest
      .requireActual<NodeCrypto>('crypto')
      .createHash('sha256')
      .update(text, 'utf8')
      .digest('hex'),
}));
// In-memory stand-in for the device file system.
jest.mock('expo-file-system', () => {
  const files = new Map<string, string>();
  const dirs = new Set<string>();
  const join = (parts: unknown[]) =>
    parts
      .map((part) => (typeof part === 'string' ? part : (part as { uri: string }).uri))
      .join('/');
  class Directory {
    uri: string;
    constructor(...parts: unknown[]) {
      this.uri = join(parts);
    }
    get exists() {
      return dirs.has(this.uri) || [...files.keys()].some((k) => k.startsWith(`${this.uri}/`));
    }
    create() {
      dirs.add(this.uri);
    }
    delete() {
      for (const key of [...files.keys()]) if (key.startsWith(`${this.uri}/`)) files.delete(key);
      dirs.delete(this.uri);
    }
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
  }
  return { Directory, File, Paths: { document: { uri: 'doc' } }, mockFiles: files };
});

const fs = jest.requireMock<{ mockFiles: Map<string, string> }>('expo-file-system');
const base64 = (bytes: Uint8Array) => btoa(String.fromCharCode(...bytes));
const privateKey = ed25519.utils.randomPrivateKey();
const KEY = {
  key_id: 'test-1',
  alg: 'Ed25519' as const,
  public_key: base64(ed25519.getPublicKey(privateKey)),
};

const guide = {
  id: 'g1',
  destination: { id: 'd-lisbon', name: 'Lisbon' },
  locale: 'en',
  title: 'Lisbon essentials',
  summary: 'How the city fits together.',
  sections: [{ id: 'intro', heading: 'Intro', body_markdown: 'Hills everywhere.', place_ids: [] }],
  tier: 'free',
  version: 1,
  content_license: 'travelbuddy-editorial',
  attribution: 'Travel Buddy editorial team',
};
const CONTENT: Record<string, string> = {
  'index.json': JSON.stringify({
    guides: [{ id: 'g1', title: guide.title, file: 'guide-a.json' }],
  }),
  'guide-a.json': JSON.stringify(guide),
};
const sha = (text: string) =>
  jest.requireActual<NodeCrypto>('crypto').createHash('sha256').update(text, 'utf8').digest('hex');
const byteLength = (text: string) => new TextEncoder().encode(text).length;

function signed(overrides: Partial<OfflineManifest> = {}): OfflineManifest {
  const body = {
    package_id: 'pkg-1',
    destination_id: 'd-lisbon',
    kind: 'guide' as const,
    locale: 'en',
    version: 1,
    files: Object.entries(CONTENT).map(([path, text]) => ({
      path,
      bytes: byteLength(text),
      sha256: sha(text),
      content_type: 'application/json',
    })),
    total_bytes: 2048,
    sha256: 'f'.repeat(64),
    min_app_version: '1.0.0',
    content_license: 'travelbuddy-editorial',
    license_expires_at: null,
    issued_at: '2026-11-10T12:00:00+00:00',
    signature_alg: 'Ed25519' as const,
    key_id: 'test-1',
    ...overrides,
  };
  const signature = ed25519.sign(new TextEncoder().encode(canonicalJson(body)), privateKey);
  return { ...body, signature: base64(signature) };
}

const pkg: OfflinePackageSummary = {
  id: 'pkg-1',
  destination_id: 'd-lisbon',
  locale: 'en',
  kind: 'guide',
  version: 1,
  total_bytes: 2048,
  tier: 'free',
  entitled: true,
  license_expires_at: null,
};

function serve(manifest: OfflineManifest, corrupt = false) {
  mockApi.post.mockResolvedValue({
    id: 'lic-1',
    package_id: 'pkg-1',
    manifest,
    download: { base_url: 'https://api.test/v1/offline-downloads/tok/', expires_at: 'x' },
    quota: { limit: 1, used: 1 },
  });
  mockApi.get.mockResolvedValue({ offline_manifest_keys: [KEY] });
  globalThis.fetch = jest.fn(async (url: string) => {
    const name = String(url).split('/').pop() ?? '';
    return { ok: true, text: async () => (corrupt ? 'tampered' : CONTENT[name]) };
  }) as unknown as typeof fetch;
}

async function renderUi(ui: ReactElement) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity, refetchInterval: false },
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
      <QueryClientProvider client={client}>{ui}</QueryClientProvider>
    </SafeAreaProvider>,
  );
}

beforeEach(async () => {
  jest.clearAllMocks();
  for (const fn of [mockApi.get, mockApi.post, mockApi.delete]) fn.mockReset();
  fs.mockFiles.clear();
  mockParams = {};
  await i18n.changeLanguage('en');
});

it('canonical JSON sorts keys at every level, like the server', () => {
  expect(canonicalJson({ b: [{ z: 1, a: null }], a: 'é' })).toBe(
    '{"a":"é","b":[{"a":null,"z":1}]}',
  );
});

it('accepts only manifests signed by a published key', () => {
  expect(verifyManifest(signed(), [KEY])).toBe(true);
  expect(verifyManifest({ ...signed(), version: 2 }, [KEY])).toBe(false);
  expect(verifyManifest(signed({ key_id: 'unknown' }), [KEY])).toBe(false);
});

it('downloads, verifies every file and reads the guide offline', async () => {
  serve(signed());
  const entry = await downloadPackage(mockApi as never, pkg, 'Lisbon');
  expect(mockApi.post).toHaveBeenCalledWith('/v1/offline-packages/pkg-1/licenses', {
    body: { device_id: 'device-0001-abcd' },
  });
  expect(entry.files).toEqual(['index.json', 'guide-a.json']);
  expect(await listDownloads()).toHaveLength(1);
  expect(await offlineGuide<typeof guide>('g1')).toEqual(guide);

  mockApi.delete.mockResolvedValue(undefined);
  await removeDownload(mockApi as never, entry);
  expect(mockApi.delete).toHaveBeenCalledWith('/v1/offline-packages/pkg-1/licenses/lic-1');
  expect(await listDownloads()).toEqual([]);
  expect(await offlineGuide('g1')).toBeNull();
});

it('rejects forged manifests and corrupted files', async () => {
  serve({ ...signed(), version: 7 });
  await expect(downloadPackage(mockApi as never, pkg, 'Lisbon')).rejects.toBeInstanceOf(
    OfflineIntegrityError,
  );
  serve(signed(), true);
  await expect(downloadPackage(mockApi as never, pkg, 'Lisbon')).rejects.toBeInstanceOf(
    OfflineIntegrityError,
  );
  expect(globalThis.fetch).toHaveBeenCalledTimes(2); // one retry, then give up
  expect(await listDownloads()).toEqual([]);
});

it('hides downloads whose content license expired', async () => {
  serve(signed({ license_expires_at: '2000-01-01T00:00:00+00:00' }));
  await downloadPackage(mockApi as never, pkg, 'Lisbon');
  expect(await listDownloads()).toEqual([]);
});

it('lists downloads with their size and removes them', async () => {
  serve(signed());
  await downloadPackage(mockApi as never, pkg, 'Lisbon');
  mockApi.delete.mockResolvedValue(undefined);
  await renderUi(<Downloads />);
  expect(await screen.findByText('Lisbon')).toBeTruthy();
  expect(screen.getByText('Using 2 KB on this device')).toBeTruthy();
  await fireEvent.press(screen.getByTestId('download-remove-pkg-1'));
  expect(
    await screen.findByText(
      "Nothing downloaded yet. Download a destination's guides from Explore.",
    ),
  ).toBeTruthy();
});

it('reads the downloaded copy of a guide when offline', async () => {
  serve(signed());
  await downloadPackage(mockApi as never, pkg, 'Lisbon');
  mockParams = { id: 'g1' };
  mockApi.get.mockRejectedValue(new ApiNetworkError('offline', 'req-1'));
  await renderUi(<GuideScreen />);
  expect(await screen.findByText("You're offline: this is your downloaded copy.")).toBeTruthy();
  expect(screen.getByText('Hills everywhere.')).toBeTruthy();
  await waitFor(() => expect(mockApi.get).toHaveBeenCalledWith('/v1/guides/g1'));
});
