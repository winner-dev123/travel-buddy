import type { Metadata } from 'next';
import type { ReactNode } from 'react';
import { notFound } from 'next/navigation';
import { getTranslations, setRequestLocale } from 'next-intl/server';
import { BarChart3, Building2, CreditCard, Flag, MapPinned, Puzzle, ScrollText, Users } from 'lucide-react';
import type { PlatformPermission } from '@travelbuddy/domain-types';
import type { LocaleCode } from '@travelbuddy/i18n';
import { AdminIdleGuard } from '@/features/admin/idle-guard';
import { Badge } from '@travelbuddy/ui';
import { Logo } from '@/components/logo';
import { Link } from '@/i18n/navigation';
import { PRIVATE_METADATA } from '@/lib/seo';
import { getMe, isStaff } from '@/server/viewer';

export const metadata: Metadata = PRIVATE_METADATA;
export const dynamic = 'force-dynamic';

/**
 * Admin area (ADR-0010). Non-staff get a 404 (existence is not revealed). The platform authorizes
 * every admin API call again with `require_platform_permission`; this check is defence in depth.
 */
export default async function AdminLayout({ children, params }: { children: ReactNode; params: Promise<{ locale: string }> }) {
  const locale = (await params).locale as LocaleCode; // validated by the root [locale] layout
  setRequestLocale(locale);
  const me = await getMe(locale);
  if (!isStaff(me.roles)) notFound();
  const t = await getTranslations('admin');
  // Navigation follows Me.permissions (contract PlatformPermission). Hiding is a convenience only:
  // every admin call is authorized again by the platform.
  const granted = new Set<PlatformPermission>(me.permissions ?? []);
  const nav = (
    [
      { href: '/admin', label: t('nav.overview'), Icon: BarChart3, permission: null },
      { href: '/admin/reports', label: t('nav.reports'), Icon: Flag, permission: 'moderation.reports.read' },
      { href: '/admin/users', label: t('nav.users'), Icon: Users, permission: 'users.read' },
      { href: '/admin/groups', label: t('nav.groups'), Icon: Building2, permission: 'moderation.reports.read' },
      { href: '/admin/challenges', label: t('nav.challenges'), Icon: Puzzle, permission: 'content.rewards.review' },
      { href: '/admin/destinations', label: t('nav.destinations'), Icon: MapPinned, permission: 'content.destinations.write' },
      { href: '/admin/billing', label: t('nav.billing'), Icon: CreditCard, permission: 'billing.configure' },
      { href: '/admin/audit', label: t('nav.audit'), Icon: ScrollText, permission: 'audit.read' },
    ] satisfies { href: string; label: string; Icon: typeof Flag; permission: PlatformPermission | null }[]
  ).filter((item) => item.permission === null || granted.has(item.permission));
  return (
    <div className="min-h-dvh md:grid md:grid-cols-[15rem_1fr]">
      <aside className="border-e border-border bg-[#0f2a2f] p-4 text-white md:sticky md:top-0 md:h-dvh">
        <div className="flex items-center justify-between gap-2">
          <Link href="/admin" className="[&_span]:text-white">
            <Logo />
          </Link>
          <Badge tone="accent">{t('badge')}</Badge>
        </div>
        <nav aria-label={t('navLabel')} className="mt-6 flex gap-1 overflow-x-auto md:flex-col">
          {nav.map(({ href, label, Icon }) => (
            <Link key={href} href={href} className="flex shrink-0 items-center gap-3 rounded-xl px-3 py-2 text-sm font-semibold text-white/80 hover:bg-white/10 hover:text-white">
              <Icon className="size-4" aria-hidden="true" />
              {label}
            </Link>
          ))}
        </nav>
        <p className="mt-6 hidden text-xs text-white/60 md:block">{t('signedInAs', { name: me.profile.display_name, roles: me.roles.join(', ') })}</p>
        <Link href="/feed" className="mt-2 hidden text-xs text-secondary underline md:block">
          {t('backToApp')}
        </Link>
      </aside>
      <main id="main" className="min-w-0 p-6 md:p-10">
        {children}
      </main>
      <AdminIdleGuard />
    </div>
  );
}
