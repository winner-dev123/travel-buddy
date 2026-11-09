'use client';

import { useEffect, useSyncExternalStore } from 'react';
import { useTranslations } from 'next-intl';
import { Monitor, Moon, Sun } from 'lucide-react';
import { cn } from '@travelbuddy/ui';

type Mode = 'light' | 'dark' | 'system';
const KEY = 'tb-theme';
const EVENT = 'tb-theme-change';

function apply(mode: Mode) {
  const dark = mode === 'dark' || (mode === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
}

function readMode(): Mode {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'light' || v === 'dark' ? v : 'system';
  } catch {
    return 'system';
  }
}

function subscribe(callback: () => void): () => void {
  window.addEventListener('storage', callback);
  window.addEventListener(EVENT, callback);
  return () => {
    window.removeEventListener('storage', callback);
    window.removeEventListener(EVENT, callback);
  };
}

function choose(next: Mode) {
  try {
    if (next === 'system') localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, next);
  } catch {
    // storage unavailable: still apply for this page view
  }
  apply(next);
  window.dispatchEvent(new Event(EVENT));
}

/** Three-way theme switch (light / dark / system), persisted per browser. */
export function ThemeToggle({ className }: { className?: string }) {
  const t = useTranslations('theme');
  const mode = useSyncExternalStore(subscribe, readMode, () => 'system' as Mode);

  useEffect(() => {
    if (mode !== 'system') return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => apply('system');
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, [mode]);

  const options: { value: Mode; label: string; Icon: typeof Sun }[] = [
    { value: 'light', label: t('light'), Icon: Sun },
    { value: 'dark', label: t('dark'), Icon: Moon },
    { value: 'system', label: t('system'), Icon: Monitor },
  ];

  return (
    <div role="radiogroup" aria-label={t('label')} className={cn('inline-flex rounded-pill border border-border bg-surface p-0.5', className)}>
      {options.map(({ value, label, Icon }) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={mode === value}
          aria-label={label}
          title={label}
          onClick={() => choose(value)}
          className={cn(
            'inline-flex size-8 items-center justify-center rounded-full text-muted-foreground transition-colors',
            'hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
            mode === value && 'bg-primary-soft text-primary',
          )}
        >
          <Icon className="size-4" aria-hidden="true" />
        </button>
      ))}
    </div>
  );
}
