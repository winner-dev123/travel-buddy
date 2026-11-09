'use client';

import type { ReactNode } from 'react';
import { useTranslations } from 'next-intl';
import { CircleUser, Compass, House, Luggage, Menu, MessageCircle, Settings, ShieldCheck, Sparkles, Users, UsersRound } from 'lucide-react';
import { Avatar, Badge, cn } from '@travelbuddy/ui';
import { LocaleSwitcher } from '@/components/locale-switcher';
import { Logo } from '@/components/logo';
import { ThemeToggle } from '@/components/theme-toggle';
import { Link, usePathname } from '@/i18n/navigation';
import { LogoutButton } from './logout-button';
import { useViewer } from './viewer-context';

const PRIMARY = [
  { href: '/feed', key: 'home', Icon: House },
  { href: '/explore', key: 'explore', Icon: Compass },
  { href: '/trips', key: 'trips', Icon: Luggage },
  { href: '/companions', key: 'companions', Icon: UsersRound },
  { href: '/groups', key: 'groups', Icon: Users },
  { href: '/messages', key: 'messages', Icon: MessageCircle },
  { href: '/profile', key: 'profile', Icon: CircleUser },
] as const;
const MOBILE = ['home', 'explore', 'trips', 'messages', 'profile'] as const;

/** Traveler app frame: desktop sidebar, mobile top bar + bottom navigation (docs/web/02). */
export function TravelerShell({ children, isStaff }: { children: ReactNode; isStaff: boolean }) {
  const t = useTranslations('shell');
  const viewer = useViewer();
  const pathname = usePathname();
  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`);

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[17rem_1fr]">
      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-dvh flex-col gap-6 border-e border-border bg-surface px-4 py-6 lg:flex">
        <Link href="/feed" className="px-2" aria-label={t('home')}>
          <Logo />
        </Link>
        <nav aria-label={t('navLabel')} className="flex flex-col gap-1">
          {PRIMARY.map(({ href, key, Icon }) => (
            <Link
              key={href}
              href={href}
              aria-current={isActive(href) ? 'page' : undefined}
              className={cn(
                'flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold transition-colors',
                isActive(href) ? 'bg-primary-soft text-primary-strong' : 'text-muted-foreground hover:bg-surface-muted hover:text-foreground',
              )}
            >
              <Icon className="size-5" aria-hidden="true" />
              {t(key)}
            </Link>
          ))}
          <Link
            href="/assistant"
            className={cn(
              'mt-2 flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold',
              isActive('/assistant') ? 'bg-accent text-accent-foreground' : 'bg-accent-soft text-foreground hover:brightness-95',
            )}
          >
            <Sparkles className="size-5" aria-hidden="true" />
            {t('assistant')}
          </Link>
        </nav>
        <div className="mt-auto flex flex-col gap-1">
          {isStaff ? (
            <Link href="/admin" className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold text-muted-foreground hover:bg-surface-muted">
              <ShieldCheck className="size-5" aria-hidden="true" />
              {t('admin')}
            </Link>
          ) : null}
          <Link href="/settings" className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold text-muted-foreground hover:bg-surface-muted">
            <Settings className="size-5" aria-hidden="true" />
            {t('settings')}
          </Link>
          <LogoutButton />
          <div className="mt-3 flex items-center gap-3 rounded-2xl border border-border p-3">
            <Avatar name={viewer.displayName} size={36} />
            <div className="flex min-w-0 flex-col">
              <span className="truncate text-sm font-semibold">{viewer.displayName}</span>
              <span className="truncate text-xs text-muted-foreground">@{viewer.handle}</span>
            </div>
            {viewer.plan === 'premium' ? (
              <Badge tone="accent" className="ms-auto">
                {t('premium')}
              </Badge>
            ) : null}
          </div>
          <div className="mt-2 flex items-center justify-between px-1">
            <LocaleSwitcher />
            <ThemeToggle />
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-col pb-20 lg:pb-0">
        {/* Mobile top bar */}
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-border bg-background/90 px-4 backdrop-blur lg:hidden">
          <Link href="/feed" aria-label={t('home')}>
            <Logo />
          </Link>
          <div className="flex items-center gap-1">
            <Link href="/assistant" className="flex size-10 items-center justify-center rounded-full text-accent hover:bg-surface-muted" aria-label={t('assistant')}>
              <Sparkles className="size-5" aria-hidden="true" />
            </Link>
            <details className="relative">
              <summary className="flex size-10 cursor-pointer list-none items-center justify-center rounded-full hover:bg-surface-muted [&::-webkit-details-marker]:hidden" aria-label={t('more')}>
                <Menu className="size-5" aria-hidden="true" />
              </summary>
              <div className="absolute end-0 top-12 z-40 flex w-64 flex-col gap-1 rounded-card border border-border bg-surface p-3 shadow-lift">
                <Link href="/companions" className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold hover:bg-surface-muted">
                  <UsersRound className="size-5" aria-hidden="true" />
                  {t('companions')}
                </Link>
                <Link href="/groups" className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold hover:bg-surface-muted">
                  <Users className="size-5" aria-hidden="true" />
                  {t('groups')}
                </Link>
                <Link href="/settings" className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold hover:bg-surface-muted">
                  <Settings className="size-5" aria-hidden="true" />
                  {t('settings')}
                </Link>
                {isStaff ? (
                  <Link href="/admin" className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-semibold hover:bg-surface-muted">
                    <ShieldCheck className="size-5" aria-hidden="true" />
                    {t('admin')}
                  </Link>
                ) : null}
                <LogoutButton />
                <div className="mt-1 flex items-center justify-between border-t border-border px-1 pt-3">
                  <LocaleSwitcher />
                  <ThemeToggle />
                </div>
              </div>
            </details>
          </div>
        </header>

        <main id="main" className="flex-1">
          {children}
        </main>

        {/* Mobile bottom navigation */}
        <nav aria-label={t('navLabel')} className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-border bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden">
          {PRIMARY.filter((p) => (MOBILE as readonly string[]).includes(p.key)).map(({ href, key, Icon }) => (
            <Link
              key={href}
              href={href}
              aria-current={isActive(href) ? 'page' : undefined}
              className={cn('flex flex-col items-center gap-0.5 py-2 text-[11px] font-semibold', isActive(href) ? 'text-primary' : 'text-muted-foreground')}
            >
              <Icon className="size-5" aria-hidden="true" />
              {t(key)}
            </Link>
          ))}
        </nav>
      </div>
    </div>
  );
}
