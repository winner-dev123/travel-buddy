'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';
import { LogOut } from 'lucide-react';
import { cn } from '@travelbuddy/ui';
import { postAuth } from '@/lib/api-browser';

export function LogoutButton({ className }: { className?: string }) {
  const t = useTranslations('shell');
  const [pending, setPending] = useState(false);
  return (
    <button
      type="button"
      disabled={pending}
      onClick={async () => {
        setPending(true);
        await postAuth('/api/auth/logout');
        // Full reload (not client navigation) so no private data survives in memory caches.
        window.location.replace('/');
      }}
      className={cn('flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold text-muted-foreground hover:bg-surface-muted hover:text-foreground disabled:opacity-60', className)}
    >
      <LogOut className="size-5" aria-hidden="true" />
      {t('logout')}
    </button>
  );
}
