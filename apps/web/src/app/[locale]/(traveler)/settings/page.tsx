import { getTranslations, setRequestLocale } from 'next-intl/server';
import type { LocaleCode } from '@travelbuddy/i18n';
import { Container } from '@travelbuddy/ui';
import { PrivacySettingsForm } from '@/features/settings/privacy-settings';
import { getMe } from '@/server/viewer';

export default async function SettingsPage({ params }: { params: Promise<{ locale: LocaleCode }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  const [me, t] = await Promise.all([getMe(locale), getTranslations('settings')]);
  return (
    <Container className="flex max-w-3xl flex-col gap-6 py-8">
      <h1 className="font-display text-3xl font-semibold">{t('title')}</h1>
      <section aria-labelledby="privacy-heading" className="flex flex-col gap-3">
        <h2 id="privacy-heading" className="text-lg font-semibold">
          {t('privacy.heading')}
        </h2>
        <PrivacySettingsForm initial={me.privacy} />
      </section>
      <p className="text-sm text-muted-foreground">{t('more')}</p>
    </Container>
  );
}
