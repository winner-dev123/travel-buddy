import { setRequestLocale } from 'next-intl/server';
import type { LocaleCode } from '@travelbuddy/i18n';
import { PostDetail } from '@/features/feed/post-detail';

export default async function PostPage({ params }: { params: Promise<{ locale: LocaleCode; postId: string }> }) {
  const { locale, postId } = await params;
  setRequestLocale(locale);
  return (
    <div className="mx-auto w-full max-w-2xl px-4 py-6">
      <PostDetail postId={postId} />
    </div>
  );
}
