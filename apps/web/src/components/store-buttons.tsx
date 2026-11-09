import { getTranslations } from 'next-intl/server';
import { Smartphone } from 'lucide-react';
import { cn } from '@travelbuddy/ui';

/**
 * App download links. Store URLs come from configuration; until they exist the buttons say
 * "coming soon" instead of linking anywhere.
 */
export async function StoreButtons({ className, tone = 'dark' }: { className?: string; tone?: 'dark' | 'light' }) {
  const t = await getTranslations('download');
  const stores = [
    { key: 'ios', label: t('appStore'), eyebrow: t('appStoreEyebrow'), url: process.env.NEXT_PUBLIC_IOS_APP_URL },
    { key: 'android', label: t('googlePlay'), eyebrow: t('googlePlayEyebrow'), url: process.env.NEXT_PUBLIC_ANDROID_APP_URL },
  ];
  const base = cn(
    'inline-flex h-14 min-w-44 items-center gap-3 rounded-2xl px-4 text-start transition-colors',
    tone === 'dark' ? 'bg-[#17252a] text-white hover:bg-black' : 'bg-white text-[#17252a] hover:bg-white/90',
  );
  return (
    <div className={cn('flex flex-wrap gap-3', className)}>
      {stores.map((s) =>
        s.url ? (
          <a key={s.key} href={s.url} className={base} rel="noopener noreferrer">
            <Smartphone className="size-6" aria-hidden="true" />
            <span className="flex flex-col leading-tight">
              <span className="text-[11px] opacity-80">{s.eyebrow}</span>
              <span className="text-base font-semibold">{s.label}</span>
            </span>
          </a>
        ) : (
          <span key={s.key} className={cn(base, 'cursor-default opacity-70')} aria-disabled="true">
            <Smartphone className="size-6" aria-hidden="true" />
            <span className="flex flex-col leading-tight">
              <span className="text-[11px] opacity-80">{t('comingSoon')}</span>
              <span className="text-base font-semibold">{s.label}</span>
            </span>
          </span>
        ),
      )}
    </div>
  );
}
