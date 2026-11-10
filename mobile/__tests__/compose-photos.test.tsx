// req: POST-002, POST-001
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import * as ImagePicker from 'expo-image-picker';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';
import { i18n } from '@/i18n';

import Compose from '../app/compose';

const mockApi = {
  get: jest.fn(),
  post: jest.fn(),
  newIdempotencyKey: jest.fn(),
};
const mockRouter = { push: jest.fn(), back: jest.fn() };
const mockUpload = jest.fn();

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({
  useRouter: () => mockRouter,
  useLocalSearchParams: () => ({}),
  Stack: { Screen: () => null },
}));
jest.mock('expo-crypto', () => ({
  randomUUID: () => '0b8c2f4e-5d6a-4b7c-8e9f-0a1b2c3d4e5f',
  CryptoDigestAlgorithm: { SHA256: 'SHA-256' },
  digest: jest.fn(async () => new Uint8Array(32).fill(0xab).buffer),
}));
jest.mock('expo-file-system', () => ({
  UploadType: { BINARY_CONTENT: 0, MULTIPART: 1 },
  File: class {
    uri: string;
    constructor(uri: string) {
      this.uri = uri;
    }
    async bytes() {
      return new Uint8Array([1, 2, 3]);
    }
    upload(url: string, options: unknown) {
      return mockUpload(this.uri, url, options);
    }
  },
}));
jest.mock('expo-image-picker', () => ({
  launchImageLibraryAsync: jest.fn(),
  launchCameraAsync: jest.fn(),
  requestCameraPermissionsAsync: jest.fn(),
  UIImagePickerPreferredAssetRepresentationMode: { Compatible: 'compatible' },
}));

const library = ImagePicker.launchImageLibraryAsync as jest.Mock;
const camera = ImagePicker.launchCameraAsync as jest.Mock;
const cameraPermission = ImagePicker.requestCameraPermissionsAsync as jest.Mock;

const SHA = 'ab'.repeat(32);

function asset(name: string, mimeType = 'image/jpeg') {
  return { uri: `file:///cache/${name}`, fileName: name, width: 1200, height: 800, mimeType };
}

const me = {
  account: { id: 'u9', email: 'me@example.com', email_verified: true, status: 'active' },
  profile: { id: 'u9', handle: 'me', display_name: 'Me', bio: null, account_visibility: 'public' },
  preferences: { ui_locale: 'en', time_zone: 'UTC' },
  privacy: { discovery_enabled: false, search_engine_indexing: false },
  roles: [],
  onboarding_completed: true,
} as unknown as Me;

let uploads = 0;

function serverAccepts() {
  mockApi.post.mockImplementation(async (path: string) => {
    if (path === '/v1/media/uploads') {
      uploads += 1;
      return {
        media_id: `m${uploads}`,
        upload: {
          method: 'PUT',
          url: `https://storage.test/q/m${uploads}`,
          headers: { 'Content-Type': 'image/jpeg' },
          expires_at: '2026-11-10T12:05:00Z',
        },
        max_bytes: 26214400,
      };
    }
    if (path.endsWith('/finalize')) return { id: path.split('/')[3], status: 'scanning' };
    return { id: 'new-post' };
  });
}

async function renderCompose() {
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
        <Compose />
      </QueryClientProvider>
    </SafeAreaProvider>,
  );
}

function postCalls(path: string) {
  return mockApi.post.mock.calls.filter(([called]) => called === path);
}

beforeEach(async () => {
  jest.clearAllMocks();
  mockApi.post.mockReset();
  mockUpload.mockReset();
  library.mockReset();
  camera.mockReset();
  cameraPermission.mockReset();
  let keys = 0;
  mockApi.newIdempotencyKey.mockImplementation(() => `key-${(keys += 1)}`);
  uploads = 0;
  mockUpload.mockResolvedValue({ status: 200, body: '', headers: {} });
  useSessionStore.getState().setSignedIn(me);
  await i18n.changeLanguage('en');
});

it('publishes a photo story: declare, upload to quarantine, finalize, attach in order', async () => {
  serverAccepts();
  library.mockResolvedValueOnce({ canceled: false, assets: [asset('a.jpg'), asset('b.jpg')] });
  await renderCompose();

  await fireEvent.press(screen.getByTestId('compose-kind-photo'));
  expect(screen.getByTestId('compose-publish')).toBeDisabled(); // a photo story needs a photo
  await fireEvent.press(screen.getByTestId('compose-add-photos'));
  expect(await screen.findByTestId('compose-photos')).toBeTruthy();
  expect(library).toHaveBeenCalledWith(
    expect.objectContaining({ mediaTypes: ['images'], selectionLimit: 10, exif: false }),
  );
  expect(screen.getByText('You can add 8 more photos.')).toBeTruthy();

  await fireEvent.press(screen.getByTestId('compose-publish')); // no text needed with photos
  await waitFor(() => expect(mockRouter.back).toHaveBeenCalled());

  expect(postCalls('/v1/media/uploads')[0][1]).toEqual({
    body: {
      purpose: 'post',
      mime_type: 'image/jpeg',
      bytes: 3,
      sha256: SHA,
      width: 1200,
      height: 800,
    },
  });
  expect(mockUpload).toHaveBeenNthCalledWith(
    1,
    'file:///cache/a.jpg',
    'https://storage.test/q/m1',
    {
      httpMethod: 'PUT',
      uploadType: 0,
      headers: { 'Content-Type': 'image/jpeg' },
    },
  );
  expect(postCalls('/v1/media/m1/finalize')).toHaveLength(1);
  expect(postCalls('/v1/media/m2/finalize')).toHaveLength(1);
  expect(postCalls('/v1/posts')[0][1]).toEqual({
    idempotencyKey: 'key-2',
    body: {
      kind: 'photo',
      body: '',
      visibility: 'public',
      location_precision: 'none',
      media_ids: ['m1', 'm2'],
    },
  });
});

it('retries only the photo that failed, with the same post request', async () => {
  serverAccepts();
  library.mockResolvedValueOnce({
    canceled: false,
    assets: [asset('a.jpg'), asset('b.png', 'image/png')],
  });
  mockUpload
    .mockResolvedValueOnce({ status: 200, body: '', headers: {} })
    .mockResolvedValueOnce({ status: 403, body: 'expired', headers: {} });
  await renderCompose();
  await fireEvent.changeText(screen.getByTestId('compose-body'), 'Sunset at Miradouro');
  await fireEvent.press(screen.getByTestId('compose-add-photos'));
  await screen.findByTestId('compose-photos');

  await fireEvent.press(screen.getByTestId('compose-publish'));
  expect(await screen.findByTestId('compose-error')).toHaveTextContent(
    "A photo didn't upload. Check your connection and try again.",
  );
  expect(postCalls('/v1/posts')).toHaveLength(0);

  await fireEvent.press(screen.getByTestId('compose-publish'));
  await waitFor(() => expect(mockRouter.back).toHaveBeenCalled());
  // a.jpg reached the server the first time; only b.png is declared again.
  expect(postCalls('/v1/media/uploads').map(([, options]) => options.body.mime_type)).toEqual([
    'image/jpeg',
    'image/png',
    'image/png',
  ]);
  expect(postCalls('/v1/media/m1/finalize')).toHaveLength(1);
  expect(postCalls('/v1/posts')).toHaveLength(1);
  expect(postCalls('/v1/posts')[0][1]).toMatchObject({
    idempotencyKey: 'key-2', // the photo set did not change between attempts
    body: { body: 'Sunset at Miradouro', media_ids: ['m1', 'm3'] },
  });
});

it('removes a photo and refuses files the server cannot process', async () => {
  library
    .mockResolvedValueOnce({ canceled: false, assets: [asset('a.jpg'), asset('b.jpg')] })
    .mockResolvedValueOnce({ canceled: false, assets: [asset('c.heic', 'image/heic')] });
  await renderCompose();
  await fireEvent.press(screen.getByTestId('compose-add-photos'));
  await screen.findByTestId('compose-photos');
  await fireEvent.press(screen.getByLabelText('Remove photo 1'));
  expect(screen.getByText('You can add 9 more photos.')).toBeTruthy();

  await fireEvent.press(screen.getByTestId('compose-add-photos'));
  expect(await screen.findByTestId('compose-photo-notice')).toHaveTextContent(
    "That file can't be used. Choose a JPEG, PNG or WebP photo.",
  );
  expect(library).toHaveBeenLastCalledWith(expect.objectContaining({ selectionLimit: 9 }));
  expect(screen.getByText('You can add 9 more photos.')).toBeTruthy();
});

it('asks for the camera in context and explains a refusal', async () => {
  cameraPermission.mockResolvedValueOnce({ granted: false });
  await renderCompose();
  await fireEvent.press(screen.getByTestId('compose-take-photo'));
  expect(await screen.findByTestId('compose-photo-notice')).toHaveTextContent(
    'Allow camera access in your phone settings to take a photo.',
  );
  expect(camera).not.toHaveBeenCalled();

  cameraPermission.mockResolvedValueOnce({ granted: true });
  camera.mockResolvedValueOnce({ canceled: false, assets: [asset('shot.jpg')] });
  await fireEvent.press(screen.getByTestId('compose-take-photo'));
  expect(await screen.findByTestId('compose-photos')).toBeTruthy();
  expect(screen.queryByTestId('compose-photo-notice')).toBeNull();
});
