import { getTranslations, setRequestLocale } from 'next-intl/server';
import { MapPin, Settings } from 'lucide-react';
import type { LocaleCode } from '@travelbuddy/i18n';
import { Avatar, Badge, Button, Card, Container } from '@travelbuddy/ui';
import { Link } from '@/i18n/navigation';
import { getMe } from '@/server/viewer';

/** Own profile (Phase 3 baseline): identity, travel styles, counts and browse destination. */
export default async function ProfilePage({ params }: { params: Promise<{ locale: LocaleCode }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const [me, t, ts] = await Promise.all([getMe(locale), getTranslations('profile'), getTranslations('travelStyles')]);
  const p = me.profile;
  return (
    <Container className="max-w-3xl py-8">
      <Card className="flex flex-col gap-5 p-6">
        <div className="flex flex-wrap items-center gap-4">
          <Avatar name={p.display_name} size={72} />
          <div className="flex min-w-0 flex-1 flex-col">
            <h1 className="font-display text-3xl font-semibold">{p.display_name}</h1>
            <p className="text-muted-foreground">@{p.handle}</p>
          </div>
          <Button asChild variant="secondary" size="sm">
            <Link href="/settings">
              <Settings aria-hidden="true" />
              {t('settings')}
            </Link>
          </Button>
        </div>
        {p.bio ? <p>{p.bio}</p> : <p className="text-muted-foreground">{t('noBio')}</p>}
        <dl className="grid grid-cols-3 gap-3 text-center">
          {(['posts', 'followers', 'following'] as const).map((k) => (
            <div key={k} className="rounded-2xl bg-surface-muted p-3">
              <dt className="text-xs text-muted-foreground">{t(`counts.${k}`)}</dt>
              <dd className="font-display text-2xl font-semibold">{p.counts[k]}</dd>
            </div>
          ))}
        </dl>
        {p.travel_styles.length > 0 ? (
          <ul className="flex flex-wrap gap-2" aria-label={t('styles')}>
            {p.travel_styles.map((s) => (
              <li key={s}>
                <Badge tone="primary">{ts(s)}</Badge>
              </li>
            ))}
          </ul>
        ) : null}
        {me.browse_destination ? (
          <p className="flex items-center gap-2 text-sm">
            <MapPin className="size-4 text-primary" aria-hidden="true" />
            {t('browsing', { name: me.browse_destination.name })}
          </p>
        ) : null}
      </Card>
    </Container>
  );
}
