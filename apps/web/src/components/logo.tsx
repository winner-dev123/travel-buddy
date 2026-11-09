import { cn } from '@travelbuddy/ui';

/** Wordmark: a compass-rose pin in brand colours + "Travel Buddy" in the display face. */
export function Logo({ className, compact = false }: { className?: string; compact?: boolean }) {
  return (
    <span className={cn('inline-flex items-center gap-2', className)}>
      {/* Solid fills only: the logo renders several times per page (e.g. a hidden desktop sidebar),
          and id-referenced gradients break when their defining instance is display:none. */}
      <svg viewBox="0 0 32 32" className="size-8 shrink-0" aria-hidden="true">
        <path d="M16 2c6.6 0 12 5.2 12 11.7C28 22 16 30 16 30S4 22 4 13.7C4 7.2 9.4 2 16 2z" fill="#087F8C" />
        <path d="M16 2c6.6 0 12 5.2 12 11.7 0 1.6-.4 3.2-1.1 4.8C24 9.5 17 6 8.6 6.9 10.8 4 13.2 2 16 2z" fill="#15B8A6" />
        <path d="M16 7.5l2.2 5.8 5.8 2.2-5.8 2.2L16 23.5l-2.2-5.8-5.8-2.2 5.8-2.2z" fill="#FFFFFF" />
        <circle cx="16" cy="15.5" r="1.6" fill="#FF735C" />
      </svg>
      {compact ? null : (
        <span className="font-display text-xl font-semibold tracking-tight text-foreground">
          Travel<span className="text-primary">Buddy</span>
        </span>
      )}
    </span>
  );
}
