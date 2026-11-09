'use client';

import { useEffect } from 'react';
import { useTranslations } from 'next-intl';
import { Button, Container } from '@travelbuddy/ui';

/** Route error boundary. Shows the digest so support can correlate with server logs. */
export default function ErrorBoundary({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const t = useTranslations('errors');
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <main id="main">
      <Container className="flex min-h-[50vh] flex-col items-center justify-center gap-4 py-20 text-center">
        <h1 className="font-display text-3xl font-semibold">{t('genericTitle')}</h1>
        <p className="max-w-md text-muted-foreground">{t('genericBody')}</p>
        {error.digest ? <p className="text-xs text-muted-foreground">{t('reference', { id: error.digest })}</p> : null}
        <Button onClick={reset}>{t('retry')}</Button>
      </Container>
    </main>
  );
}
