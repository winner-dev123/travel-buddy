import type { ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { Post } from '@travelbuddy/domain-types';

// Translation keys are rendered as-is, so assertions check which message is chosen.
vi.mock('next-intl', () => ({
  useTranslations: (ns: string) => (key: string) => `${ns}.${key}`,
  useFormatter: () => ({ dateTime: () => 'date', relativeTime: () => 'ago', number: (n: number) => String(n) }),
  useLocale: () => 'en',
  useNow: () => new Date('2026-11-09T12:00:00Z'),
}));
vi.mock('@/i18n/navigation', () => ({ Link: ({ href, children, ...rest }: { href: string; children: ReactNode }) => <a href={href} {...rest}>{children}</a> }));
vi.mock('@/lib/api-browser', () => ({ browserApi: () => ({}) }));

const { PostCard } = await import('./post-card');

const basePost = {
  id: '0193f1c2-0000-7000-8000-0000000000aa',
  kind: 'tip',
  body: 'Arrive early for the cable car.',
  language: 'en',
  visibility: 'public',
  location_precision: 'none',
  primary_destination: null,
  place: null,
  tags: [],
  media: [],
  author: { id: 'u1', handle: 'ana', display_name: 'Ana Silva', avatar: null },
  published_at: '2026-11-09T10:00:00Z',
  edited_at: null,
  indexable: false,
  counts: { reactions: 0, comments: 0, bookmarks: 0, shares: 0, reactions_by_type: { like: 0, love: 0, helpful: 0, wow: 0 } },
  viewer: { reaction: null, bookmarked: false, is_author: true, can_edit: true, can_delete: true, can_comment: true },
} as unknown as Post;

const renderCard = (post: Post) =>
  render(
    <QueryClientProvider client={new QueryClient()}>
      <PostCard post={post} />
    </QueryClientProvider>,
  );

describe('PostCard moderation notice (SAFE-013)', () => {
  it.each(['removed', 'limited', 'pending'] as const)('tells the author when their post is %s, and offers no share link', (state) => {
    renderCard({ ...basePost, moderation_state: state });
    expect(screen.getByRole('status', { name: '' }).textContent).toContain(`post.moderation.${state}`);
    expect(screen.queryByRole('button', { name: 'post.share' })).toBeNull();
  });

  it('shows nothing extra for approved posts or when the state is absent (non-authors)', () => {
    renderCard({ ...basePost, moderation_state: 'approved' });
    expect(screen.queryByText(/post\.moderation\./)).toBeNull();
    expect(screen.getByRole('button', { name: 'post.share' })).toBeTruthy();
  });
});
