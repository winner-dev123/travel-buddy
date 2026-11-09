'use client';

import { useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { ArrowRight } from 'lucide-react';
import { Alert, Avatar, cn } from '@travelbuddy/ui';
import { postAuth } from '@/lib/api-browser';

export interface PersonaOption {
  sub: string;
  handle: string;
  display_name: string;
  email: string;
  note: string;
}

/** Development identity provider UI (dev/test only). Signs in as a seeded persona. */
export function DevPersonaPicker({ personas, next }: { personas: PersonaOption[]; next: string }) {
  const t = useTranslations('auth.dev');
  const locale = useLocale();
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState(false);

  const signIn = async (p: PersonaOption) => {
    setPending(p.sub);
    setError(false);
    const res = await postAuth<{ redirect?: string }>('/api/auth/dev', { mode: 'login', sub: p.sub, email: p.email, name: p.display_name, next, locale });
    if (res.ok && res.data.redirect) {
      window.location.assign(res.data.redirect);
    } else {
      setError(true);
      setPending(null);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      {error ? <Alert tone="danger">{t('error')}</Alert> : null}
      <ul className="flex flex-col gap-2">
        {personas.map((p) => (
          <li key={p.sub}>
            <button
              type="button"
              disabled={pending !== null}
              onClick={() => signIn(p)}
              className={cn(
                'flex w-full items-center gap-3 rounded-2xl border border-border bg-surface px-4 py-3 text-start transition-colors',
                'hover:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60',
              )}
            >
              <Avatar name={p.display_name} size={40} />
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="font-semibold">{p.display_name}</span>
                <span className="truncate text-xs text-muted-foreground">{p.note}</span>
              </span>
              <ArrowRight className={cn('size-4 text-muted-foreground rtl:rotate-180', pending === p.sub && 'animate-pulse')} aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
