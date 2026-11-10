// req: POST-010, I18N-006
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import { ApiProblem } from '@/api';
import { PostCard } from '@/features/feed/PostCard';
import type { Post } from '@/features/feed/types';
import { i18n } from '@/i18n';

const mockApi = {
  get: jest.fn(),
  post: jest.fn(),
  put: jest.fn(),
  patch: jest.fn(),
  delete: jest.fn(),
  newIdempotencyKey: jest.fn(() => 'key-1'),
};

jest.mock('@/api', () => ({ ...jest.requireActual('@/api'), getApiClient: () => mockApi }));

const TEXT = 'Chegue cedo à praia, a luz é maravilhosa.';

function post(overrides: Partial<Post> = {}): Post {
  return {
    id: 'p1',
    author: { id: 'u1', handle: 'ana', display_name: 'Ana Souza', avatar: null },
    kind: 'tip',
    body: TEXT,
    language: 'pt-BR',
    visibility: 'public',
    primary_destination: null,
    tags: [],
    media: [],
    published_at: '2026-11-09T10:00:00Z',
    edited_at: null,
    counts: { reactions: 0, comments: 0, bookmarks: 0, shares: 0 },
    viewer: {
      reaction: null,
      bookmarked: false,
      is_author: false,
      can_comment: true,
      can_delete: false,
    },
    ...overrides,
  } as Post;
}

beforeEach(async () => {
  jest.clearAllMocks();
  for (const fn of [mockApi.get, mockApi.post]) fn.mockReset();
  await i18n.changeLanguage('en');
});

it('offers a labelled machine translation and the original stays one tap away', async () => {
  mockApi.get.mockResolvedValue({
    post_id: 'p1',
    source_language: 'pt-BR',
    target_language: 'en',
    text: 'Get to the beach early, the light is wonderful.',
    machine_translated: true,
  });
  await render(<PostCard post={post()} />);
  await fireEvent.press(screen.getByTestId('post-translate-p1'));
  expect(await screen.findByText('Get to the beach early, the light is wonderful.')).toBeTruthy();
  expect(screen.getByTestId('post-translated-p1')).toHaveTextContent(/^Machine-translated from /);
  expect(mockApi.get).toHaveBeenCalledWith('/v1/posts/p1/translation', {
    query: { target: 'en' },
  });
  await fireEvent.press(screen.getByTestId('post-original-p1'));
  expect(screen.getByText(TEXT)).toBeTruthy();
});

it('asks for consent once, then translates', async () => {
  mockApi.get
    .mockRejectedValueOnce(
      new ApiProblem(
        { status: 403, code: 'consent_required', title: 'Forbidden', type: 'x' },
        'req-1',
      ),
    )
    .mockResolvedValueOnce({
      post_id: 'p1',
      source_language: 'pt-BR',
      target_language: 'en',
      text: 'Translated.',
      machine_translated: true,
    });
  mockApi.post.mockResolvedValue({});
  await render(<PostCard post={post()} />);
  await fireEvent.press(screen.getByTestId('post-translate-p1'));
  await fireEvent.press(await screen.findByTestId('post-allow-translation-p1'));
  expect(await screen.findByText('Translated.')).toBeTruthy();
  await waitFor(() =>
    expect(mockApi.post).toHaveBeenCalledWith('/v1/users/me/consents', {
      body: {
        consent_type: 'post_translation',
        version: '2026-11-01',
        granted: true,
        source: 'prompt',
      },
    }),
  );
});

it('does not offer translation for posts in my language or to guests', async () => {
  await render(<PostCard post={post({ language: 'en' })} />);
  expect(screen.queryByTestId('post-translate-p1')).toBeNull();
  await render(<PostCard post={post()} interactive={false} />);
  expect(screen.queryByTestId('post-translate-p1')).toBeNull();
});
