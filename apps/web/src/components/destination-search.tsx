'use client';

import { useEffect, useId, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslations } from 'next-intl';
import { MapPin, Search } from 'lucide-react';
import type { DestinationSummary } from '@travelbuddy/domain-types';
import { cn, Spinner } from '@travelbuddy/ui';
import { browserApi } from '@/lib/api-browser';
import { qk } from '@/lib/query-keys';

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}

/**
 * Accessible destination autocomplete (WAI-ARIA combobox pattern). Calls the platform search
 * through the BFF. `onSelect` decides what happens (navigate, set feed filter, …).
 */
export function DestinationSearch({
  onSelect,
  placeholder,
  label,
  size = 'md',
  className,
  autoFocus,
}: {
  onSelect: (destination: DestinationSummary) => void;
  placeholder?: string;
  label: string;
  size?: 'md' | 'lg';
  className?: string;
  autoFocus?: boolean;
}) {
  const t = useTranslations('search');
  const id = useId();
  const listId = `${id}-list`;
  const [term, setTerm] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const q = useDebounced(term.trim(), 250);

  const { data, isFetching, isError } = useQuery({
    queryKey: qk.destinationSearch(q),
    queryFn: ({ signal }) => {
      void signal;
      return browserApi().destinations.search(q, { limit: 8 });
    },
    enabled: q.length >= 2,
    staleTime: 5 * 60_000,
  });
  const results = q.length >= 2 ? (data?.data ?? []) : [];

  const choose = (d: DestinationSummary) => {
    setOpen(false);
    setTerm(d.name);
    onSelect(d);
  };

  return (
    <div className={cn('relative', className)}>
      <label htmlFor={id} className="sr-only">
        {label}
      </label>
      <div
        className={cn(
          'flex items-center gap-3 rounded-pill border border-border bg-surface ps-5 pe-2 shadow-card focus-within:ring-2 focus-within:ring-ring',
          size === 'lg' ? 'h-16' : 'h-12',
        )}
      >
        <Search className="size-5 shrink-0 text-muted-foreground" aria-hidden="true" />
        <input
          ref={inputRef}
          id={id}
          role="combobox"
          aria-expanded={open && term.trim().length >= 2}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
          autoComplete="off"
          autoFocus={autoFocus}
          value={term}
          placeholder={placeholder ?? t('placeholder')}
          onChange={(e) => {
            setTerm(e.target.value);
            setOpen(true);
            setActive(-1);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 120)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') {
              e.preventDefault();
              setOpen(true);
              setActive((i) => Math.min(results.length - 1, i + 1));
            } else if (e.key === 'ArrowUp') {
              e.preventDefault();
              setActive((i) => Math.max(-1, i - 1));
            } else if (e.key === 'Enter' && active >= 0 && results[active]) {
              e.preventDefault();
              choose(results[active]);
            } else if (e.key === 'Escape') {
              setOpen(false);
            }
          }}
          className={cn('min-w-0 flex-1 bg-transparent text-foreground placeholder:text-muted-foreground focus:outline-none', size === 'lg' ? 'text-lg' : 'text-sm')}
        />
        {isFetching ? <Spinner className="me-3 size-4 text-muted-foreground" /> : null}
      </div>

      {open && term.trim().length >= 2 ? (
        <ul
          id={listId}
          role="listbox"
          aria-label={label}
          className="absolute inset-x-0 top-full z-40 mt-2 max-h-80 overflow-y-auto rounded-2xl border border-border bg-surface p-1.5 shadow-lift"
        >
          {results.map((d, i) => (
            <li
              key={d.id}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => {
                e.preventDefault();
                choose(d);
              }}
              onMouseEnter={() => setActive(i)}
              className={cn('flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5', i === active && 'bg-primary-soft')}
            >
              <MapPin className="size-4 shrink-0 text-primary" aria-hidden="true" />
              <span className="flex min-w-0 flex-col">
                <span className="truncate font-semibold">{d.name}</span>
                <span className="truncate text-xs text-muted-foreground">
                  {[t(`kind.${d.kind}`), d.country_name].filter(Boolean).join(' · ')}
                </span>
              </span>
            </li>
          ))}
          {!isFetching && results.length === 0 ? (
            <li className="px-3 py-3 text-sm text-muted-foreground" role="presentation">
              {isError ? t('error') : t('noResults')}
            </li>
          ) : null}
        </ul>
      ) : null}
    </div>
  );
}
