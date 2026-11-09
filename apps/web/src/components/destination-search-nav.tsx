'use client';

import { useTranslations } from 'next-intl';
import { useRouter } from '@/i18n/navigation';
import { destinationHref } from '@/lib/paths';
import { DestinationSearch } from './destination-search';

/** Public-site search box: selecting a result opens its destination page. */
export function DestinationSearchNav({ size = 'lg', className }: { size?: 'md' | 'lg'; className?: string }) {
  const t = useTranslations('search');
  const router = useRouter();
  return (
    <DestinationSearch
      size={size}
      className={className}
      label={t('label')}
      onSelect={(d) => {
        // Neighbourhood pages don't exist yet; open the nearest public page (city or country).
        const parts = d.path.split('/');
        router.push(destinationHref(parts.slice(0, Math.min(parts.length, 2)).join('/')));
      }}
    />
  );
}
