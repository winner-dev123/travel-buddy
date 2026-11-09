import { getTranslations } from 'next-intl/server';
import { Container } from '@travelbuddy/ui';
import { Link } from '@/i18n/navigation';
import { Logo } from './logo';
import { LocaleSwitcher } from './locale-switcher';
import { ThemeToggle } from './theme-toggle';

export async function SiteFooter() {
  const t = await getTranslations('footer');
  const columns = [
    {
      title: t('explore'),
      links: [
        { href: '/destinations', label: t('destinations') },
        { href: '/stories', label: t('stories') },
        { href: '/pricing', label: t('premium') },
      ],
    },
    {
      title: t('company'),
      links: [
        { href: '/about', label: t('about') },
        { href: '/download', label: t('apps') },
      ],
    },
    {
      title: t('legal'),
      links: [
        { href: '/legal/terms', label: t('terms') },
        { href: '/legal/privacy', label: t('privacy') },
        { href: '/legal/cookies', label: t('cookies') },
        { href: '/legal/community-guidelines', label: t('guidelines') },
      ],
    },
  ] as const;

  return (
    <footer className="mt-24 border-t border-border bg-surface">
      <Container className="grid gap-10 py-14 md:grid-cols-[1.4fr_repeat(3,1fr)]">
        <div className="flex flex-col gap-4">
          <Logo />
          <p className="max-w-xs text-sm text-muted-foreground">{t('tagline')}</p>
          <div className="flex flex-wrap items-center gap-3">
            <LocaleSwitcher />
            <ThemeToggle />
          </div>
        </div>
        {columns.map((col) => (
          <nav key={col.title} aria-label={col.title} className="flex flex-col gap-2">
            <h2 className="text-sm font-bold">{col.title}</h2>
            {col.links.map((l) => (
              <Link key={l.href} href={l.href} className="text-sm text-muted-foreground hover:text-foreground hover:underline">
                {l.label}
              </Link>
            ))}
          </nav>
        ))}
      </Container>
      <div className="border-t border-border">
        <Container className="flex flex-col gap-2 py-6 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
          <p>{t('copyright', { year: new Date().getFullYear() })}</p>
          <p>{t('noLiveInfo')}</p>
        </Container>
      </div>
    </footer>
  );
}
