import Image from 'next/image';
import type { MediaRef } from '@travelbuddy/domain-types';
import { cn } from '@travelbuddy/ui';
import { DestinationArt } from './destination-art';

/**
 * Renders platform media with its required attribution (contract: MediaRef.attribution must be
 * shown wherever editorial/licensed media appears), or a branded placeholder when there is none.
 */
export function MediaImage({
  media,
  seed,
  hints,
  sizes,
  priority = false,
  className,
  showAttribution = true,
}: {
  media: MediaRef | null | undefined;
  seed: string;
  hints?: readonly string[];
  sizes: string;
  priority?: boolean;
  className?: string;
  showAttribution?: boolean;
}) {
  if (!media || media.status !== 'ready' || !media.url || media.kind !== 'image') {
    return (
      <div className={cn('relative overflow-hidden', className)}>
        <DestinationArt seed={seed} categories={hints} />
      </div>
    );
  }
  return (
    <figure className={cn('relative overflow-hidden', className)}>
      <Image src={media.url} alt={media.alt_text ?? ''} fill sizes={sizes} priority={priority} className="object-cover" />
      {showAttribution && media.attribution ? (
        <figcaption className="absolute end-2 bottom-2 max-w-[80%] truncate rounded bg-black/55 px-2 py-0.5 text-[10px] text-white">
          {media.attribution.url ? (
            <a href={media.attribution.url} rel="noopener noreferrer license" target="_blank" className="underline">
              {media.attribution.text}
            </a>
          ) : (
            media.attribution.text
          )}{' '}
          · {media.attribution.license}
        </figcaption>
      ) : null}
    </figure>
  );
}
