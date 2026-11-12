// req: DM-015, NOTIF-006, NFR-008
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { router } from 'expo-router';

import { useSessionStore } from '@/auth/sessionStore';
import type { Me } from '@/auth/types';
import { InAppBannerHost, useBannerStore } from '@/components/InAppBanner';
import { i18n } from '@/i18n';
import {
  DEFAULT_CHAT_PREFERENCES,
  hydrateChatPreferences,
  useChatPreferences,
} from '@/state/chatPreferences';

import ChatSettings from '../app/settings/chat';

const mockApi = { get: jest.fn() };
jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));
jest.mock('expo-router', () => ({ Stack: { Screen: () => null }, router: { push: jest.fn() } }));
// In-memory stand-in for the device file system, with downloads.
jest.mock('expo-file-system', () => {
  const files = new Map<string, string>();
  const name = (part: unknown) => (typeof part === 'string' ? part : (part as { uri: string }).uri);
  class Directory {
    uri: string;
    constructor(...parts: unknown[]) {
      this.uri = parts.map(name).join('/');
    }
    get exists() {
      return true;
    }
    create() {}
  }
  class File {
    uri: string;
    constructor(...parts: unknown[]) {
      this.uri = parts.map(name).join('/');
    }
    get exists() {
      return files.has(this.uri);
    }
    textSync() {
      return files.get(this.uri) ?? '';
    }
    writeSync(text: string) {
      files.set(this.uri, text);
    }
    delete() {
      files.delete(this.uri);
    }
    static downloadFileAsync = jest.fn(async (url: string, target: File) => {
      files.set(target.uri, `downloaded ${url}`);
      return target;
    });
  }
  return { File, Directory, Paths: { document: { uri: 'doc' } }, mockFiles: files };
});

const fs = jest.requireMock<{
  mockFiles: Map<string, string>;
  File: { downloadFileAsync: jest.Mock };
}>('expo-file-system');

const me: Me = {
  account: {
    id: 'u9',
    email: 'me@example.com',
    email_verified: true,
    status: 'active',
    primary_locale: 'en',
  },
  profile: { id: 'u9', handle: 'me', display_name: 'Me', bio: null, account_visibility: 'public' },
  preferences: { ui_locale: 'en', time_zone: 'UTC' },
  privacy: { discovery_enabled: false, search_engine_indexing: false },
  roles: [],
  onboarding_completed: true,
};

function photo(id: string) {
  return { id, kind: 'image', status: 'ready', url: `https://cdn.test/${id}.jpg`, alt_text: null };
}

async function renderUi(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
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
  fs.mockFiles.clear();
  useChatPreferences.setState({ ...DEFAULT_CHAT_PREFERENCES });
  useSessionStore.getState().setSignedIn(me);
  await i18n.changeLanguage('en');
});

describe('chat settings', () => {
  it('moves the send button to the left for left hands and remembers it', async () => {
    mockApi.get.mockResolvedValue({ data: [], page: { next_cursor: null, has_more: false } });
    await renderUi(<ChatSettings />);
    expect(screen.getByTestId('chat-settings-preview-right')).toBeTruthy();
    expect(screen.getByTestId('chat-send-side-right')).toBeSelected();

    await fireEvent.press(screen.getByTestId('chat-send-side-left'));
    expect(useChatPreferences.getState().sendSide).toBe('left');
    expect(screen.getByTestId('chat-settings-preview-left')).toBeTruthy();

    // After a restart the choice comes back from the file.
    useChatPreferences.setState({ ...DEFAULT_CHAT_PREFERENCES });
    hydrateChatPreferences();
    expect(useChatPreferences.getState().sendSide).toBe('left');
  });

  it('offers at least two built-in trip backgrounds', async () => {
    mockApi.get.mockResolvedValue({ data: [], page: { next_cursor: null, has_more: false } });
    await renderUi(<ChatSettings />);
    expect(screen.getByTestId('chat-bg-none')).toBeSelected();
    expect(screen.getByTestId('chat-bg-coast')).toBeTruthy();
    expect(screen.getByTestId('chat-bg-mountains')).toBeTruthy();
    expect(screen.queryByTestId('chat-settings-preview-background')).toBeNull();

    await fireEvent.press(screen.getByTestId('chat-bg-mountains'));
    expect(useChatPreferences.getState().background).toEqual({ kind: 'builtin', id: 'mountains' });
    expect(screen.getByTestId('chat-settings-preview-background')).toBeTruthy();
    expect(await screen.findByTestId('chat-bg-no-photos')).toBeTruthy();
  });

  it("uses a photo from the traveller's own stories, saved into the app", async () => {
    mockApi.get.mockResolvedValue({
      data: [
        { id: 'p1', media: [photo('a1'), { ...photo('v1'), kind: 'video' }] },
        { id: 'p2', media: [photo('a2'), photo('a1')] },
      ],
      page: { next_cursor: null, has_more: false },
    });
    await renderUi(<ChatSettings />);
    expect(mockApi.get).toHaveBeenCalledWith('/v1/users/u9/posts', { query: { limit: 20 } });
    expect(await screen.findByTestId('chat-bg-photo-a1')).toBeTruthy();
    expect(screen.getByTestId('chat-bg-photo-a2')).toBeTruthy();
    expect(screen.queryByTestId('chat-bg-photo-v1')).toBeNull(); // videos aren't backgrounds

    await fireEvent.press(screen.getByTestId('chat-bg-photo-a2'));
    await waitFor(() =>
      expect(useChatPreferences.getState().background).toEqual({
        kind: 'photo',
        mediaId: 'a2',
        uri: 'doc/chat-backgrounds/a2.jpg',
      }),
    );
    expect(fs.File.downloadFileAsync).toHaveBeenCalledWith(
      'https://cdn.test/a2.jpg',
      expect.objectContaining({ uri: 'doc/chat-backgrounds/a2.jpg' }),
    );

    // Switching photos removes the previous copy.
    await fireEvent.press(screen.getByTestId('chat-bg-photo-a1'));
    await waitFor(() =>
      expect(useChatPreferences.getState().background).toMatchObject({ mediaId: 'a1' }),
    );
    expect(fs.mockFiles.has('doc/chat-backgrounds/a2.jpg')).toBe(false);
  });

  it('says so when a photo could not be saved', async () => {
    mockApi.get.mockResolvedValue({
      data: [{ id: 'p1', media: [photo('a1')] }],
      page: { next_cursor: null, has_more: false },
    });
    fs.File.downloadFileAsync.mockRejectedValueOnce(new Error('offline'));
    await renderUi(<ChatSettings />);
    await fireEvent.press(await screen.findByTestId('chat-bg-photo-a1'));
    expect(await screen.findByTestId('chat-bg-failed')).toHaveTextContent(
      "Couldn't save that photo. Check your connection and try again.",
    );
    expect(useChatPreferences.getState().background).toEqual({ kind: 'none' });
  });
});

describe('in-app banner', () => {
  it('shows a friend request at once and opens Companions when tapped', async () => {
    await renderUi(<InAppBannerHost />);
    expect(screen.queryByTestId('in-app-banner')).toBeNull();
    await act(async () => {
      useBannerStore.getState().show({
        id: 'n1',
        title: 'New connection request',
        body: 'Bo wants to connect',
        user: { id: 'u2', handle: 'bo', display_name: 'Bo', avatar: null },
        href: '/(tabs)/companions',
      });
    });
    expect(screen.getByTestId('in-app-banner')).toHaveTextContent(
      /New connection request\s*Bo wants to connect$/,
    );
    await fireEvent.press(screen.getByTestId('in-app-banner'));
    expect(router.push).toHaveBeenCalledWith('/(tabs)/companions');
    expect(screen.queryByTestId('in-app-banner')).toBeNull();
  });

  it('hides itself after a few seconds', async () => {
    jest.useFakeTimers();
    try {
      await renderUi(<InAppBannerHost />);
      await act(async () => {
        useBannerStore
          .getState()
          .show({ id: 'n2', title: 'Request accepted', body: 'Bo accepted', user: null });
      });
      expect(screen.getByTestId('in-app-banner')).toBeTruthy();
      await act(async () => {
        jest.advanceTimersByTime(6000);
      });
      expect(screen.queryByTestId('in-app-banner')).toBeNull();
    } finally {
      jest.useRealTimers();
    }
  });
});
