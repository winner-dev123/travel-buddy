import { getTranslations } from 'next-intl/server';
import { Menu } from 'lucide-react';
import { Button, Container } from '@travelbuddy/ui';
import { Link } from '@/i18n/navigation';
import { Logo } from './logo';
import { LocaleSwitcher } from './locale-switcher';
import { ThemeToggle } from './theme-toggle';

/** Public header. The mobile menu is a native <details> disclosure: no JavaScript required. */
export async function SiteHeader() {
  const t = await getTranslations('nav');
  const links = [
    { href: '/destinations', label: t('destinations') },
    { href: '/stories', label: t('stories') },
    { href: '/pricing', label: t('pricing') },
    { href: '/download', label: t('download') },
  ] as const;

  return (
    <header className="sticky top-0 z-30 border-b border-border/70 bg-background/85 backdrop-blur-md supports-[backdrop-filter]:bg-background/70">
      <Container className="flex h-16 items-center justify-between gap-4">
        <Link href="/" className="rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label={t('home')}>
          <Logo />
        </Link>

        <nav aria-label={t('primary')} className="hidden items-center gap-1 lg:flex">
          {links.map((l) => (
            <Link key={l.href} href={l.href} className="rounded-pill px-3 py-2 text-sm font-semibold text-muted-foreground transition-colors hover:bg-surface-muted hover:text-foreground">
              {l.label}
            </Link>
          ))}
        </nav>

        <div className="hidden items-center gap-3 lg:flex">
          <LocaleSwitcher />
          <ThemeToggle />
          <Button asChild variant="ghost" size="sm">
            <Link href="/login">{t('login')}</Link>
          </Button>
          <Button asChild variant="accent" size="sm">
            <Link href="/register">{t('join')}</Link>
          </Button>
        </div>

        <details className="group relative lg:hidden">
          <summary
            className="flex size-10 cursor-pointer list-none items-center justify-center rounded-full hover:bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden"
            aria-label={t('menu')}
          >
            <Menu className="size-5" aria-hidden="true" />
          </summary>
          <div className="absolute end-0 top-12 w-[min(20rem,calc(100vw-2rem))] rounded-card border border-border bg-surface p-4 shadow-lift">
            <nav aria-label={t('primary')} className="flex flex-col">
              {links.map((l) => (
                <Link key={l.href} href={l.href} className="rounded-lg px-3 py-2.5 font-semibold hover:bg-surface-muted">
                  {l.label}
                </Link>
              ))}
            </nav>
            <div className="mt-3 flex items-center justify-between border-t border-border pt-3">
              <LocaleSwitcher />
              <ThemeToggle />
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2">
              <Button asChild variant="secondary" size="sm">
                <Link href="/login">{t('login')}</Link>
              </Button>
              <Button asChild variant="accent" size="sm">
                <Link href="/register">{t('join')}</Link>
              </Button>
            </div>
          </div>
        </details>
      </Container>
    </header>
  );
}
