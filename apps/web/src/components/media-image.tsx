import Image from 'next/image';
import type { MediaAttribution, MediaRef } from '@travelbuddy/domain-types';
import { cn } from '@travelbuddy/ui';
import { DestinationArt } from './destination-art';

/** True when the media can be rendered as an image (otherwise callers show a placeholder). */
export function isRenderableImage(media: MediaRef | null | undefined): media is MediaRef & { url: string } {
  return Boolean(media && media.status === 'ready' && media.url && media.kind === 'image');
}

/**
 * Credit line for editorial/licensed media ("Author / Source · Licence"). Use `as="text"` inside
 * an interactive parent (a card link), where a nested link is not allowed.
 */
export function MediaCredit({
  attribution,
  as = 'link',
  className,
}: {
  attribution: MediaAttribution;
  as?: 'link' | 'text';
  className?: string;
}) {
  return (
    <span className={cn('block max-w-full truncate rounded bg-black/65 px-2 py-0.5 text-[10px] leading-4 text-white', className)}>
      {as === 'link' && attribution.url ? (
        <a href={attribution.url} rel="noopener noreferrer license" target="_blank" className="underline underline-offset-2 hover:no-underline">
          {attribution.text}
        </a>
      ) : (
        attribution.text
      )}{' '}
      · {attribution.license}
    </span>
  );
}

/**
 * Renders platform media with its required attribution (contract: MediaRef.attribution must be
 * shown wherever editorial/licensed media appears), or a branded placeholder when there is none.
 *
 * `credit`: "link" overlays a linked credit; "text" overlays a plain credit (for use inside links);
 * "none" when the caller renders <MediaCredit> itself (e.g. above foreground content).
 */
export function MediaImage({
  media,
  seed,
  hints,
  sizes,
  priority = false,
  className,
  credit = 'link',
  creditClassName,
}: {
  media: MediaRef | null | undefined;
  seed: string;
  hints?: readonly string[];
  sizes: string;
  priority?: boolean;
  className?: string;
  credit?: 'link' | 'text' | 'none';
  creditClassName?: string;
}) {
  if (!isRenderableImage(media)) {
    return (
      <div className={cn('relative overflow-hidden', className)}>
        <DestinationArt seed={seed} categories={hints} />
      </div>
    );
  }
  return (
    <figure className={cn('relative overflow-hidden', className)}>
      <Image src={media.url} alt={media.alt_text ?? ''} fill sizes={sizes} priority={priority} className="object-cover" />
      {credit !== 'none' && media.attribution ? (
        <figcaption className={cn('absolute end-2 bottom-2 max-w-[80%]', creditClassName)}>
          <MediaCredit attribution={media.attribution} as={credit} />
        </figcaption>
      ) : null}
    </figure>
  );
}
