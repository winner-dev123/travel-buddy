import { getTranslations } from 'next-intl/server';
import { ArrowUpRight } from 'lucide-react';
import type { DestinationSummary } from '@travelbuddy/domain-types';
import { Badge, cn } from '@travelbuddy/ui';
import { Link } from '@/i18n/navigation';
import { destinationHref } from '@/lib/paths';
import { MediaImage } from './media-image';

export async function DestinationCard({
  destination,
  size = 'md',
  priority = false,
}: {
  destination: DestinationSummary;
  size?: 'md' | 'lg';
  priority?: boolean;
}) {
  const t = await getTranslations('continents');
  return (
    <Link
      href={destinationHref(destination.path)}
      className={cn(
        'group relative isolate flex flex-col justify-end overflow-hidden rounded-card bg-surface-muted shadow-card',
        'transition-transform duration-300 ease-travel hover:-translate-y-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 motion-reduce:hover:translate-y-0',
        size === 'lg' ? 'aspect-[4/5] sm:aspect-[3/4]' : 'aspect-[4/5]',
      )}
    >
      <MediaImage
        media={destination.cover}
        seed={destination.id}
        sizes={size === 'lg' ? '(min-width: 1024px) 40vw, 90vw' : '(min-width: 1024px) 22vw, (min-width: 640px) 45vw, 90vw'}
        priority={priority}
        showAttribution={false}
        className="absolute inset-0 -z-10 transition-transform duration-700 ease-travel group-hover:scale-105 motion-reduce:group-hover:scale-100"
      />
      <div className="absolute inset-0 -z-10 bg-gradient-to-t from-black/75 via-black/20 to-transparent" aria-hidden="true" />
      <div className="flex flex-col gap-1.5 p-5 text-white">
        {destination.continent ? (
          <Badge tone="inverse" className="w-fit">
            {t(destination.continent)}
          </Badge>
        ) : null}
        <h3 className={cn('font-display font-semibold leading-tight', size === 'lg' ? 'text-3xl' : 'text-2xl')}>
          {destination.name}
        </h3>
        {destination.country_name ? <p className="text-sm font-medium text-white/85">{destination.country_name}</p> : null}
        {destination.tagline ? <p className="line-clamp-2 text-sm text-white/80">{destination.tagline}</p> : null}
        <ArrowUpRight className="absolute end-4 top-4 size-5 text-white/90 opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
      </div>
    </Link>
  );
}
