import { useTranslations } from 'next-intl';
import { Compass } from 'lucide-react';
import { Button, Container } from '@travelbuddy/ui';
import { Link } from '@/i18n/navigation';

export default function NotFound() {
  const t = useTranslations('errors');
  return (
    <main id="main">
      <Container className="flex min-h-[60vh] flex-col items-center justify-center gap-5 py-20 text-center">
        <span className="flex size-14 items-center justify-center rounded-full bg-primary-soft text-primary">
          <Compass className="size-7" aria-hidden="true" />
        </span>
        <h1 className="font-display text-4xl font-semibold">{t('notFoundTitle')}</h1>
        <p className="max-w-md text-muted-foreground">{t('notFoundBody')}</p>
        <div className="flex gap-3">
          <Button asChild>
            <Link href="/">{t('home')}</Link>
          </Button>
          <Button asChild variant="secondary">
            <Link href="/destinations">{t('destinations')}</Link>
          </Button>
        </div>
      </Container>
    </main>
  );
}
