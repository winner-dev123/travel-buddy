import { getTranslations } from 'next-intl/server';
import { Construction } from 'lucide-react';
import { Container, EmptyState } from '@travelbuddy/ui';

export type ComingSoonSection =
  | 'explore'
  | 'trips'
  | 'companions'
  | 'groups'
  | 'messages'
  | 'assistant'
  | 'saved'
  | 'notifications'
  | 'membership';

const PHASE: Record<ComingSoonSection, number> = {
  explore: 6,
  trips: 6,
  companions: 4,
  groups: 5,
  messages: 4,
  assistant: 6,
  saved: 6,
  notifications: 4,
  membership: 5,
};

/**
 * Honest placeholder for sections whose backend modules and UI are scheduled for later phases
 * (docs/web/09-backlog.md). No fake data, no simulated behaviour.
 */
export async function ComingSoon({ section }: { section: ComingSoonSection }) {
  const t = await getTranslations('comingSoon');
  return (
    <Container className="max-w-3xl py-10">
      <h1 className="font-display text-3xl font-semibold">{t(`${section}.title`)}</h1>
      <EmptyState
        className="mt-8"
        icon={<Construction />}
        title={t('heading', { phase: PHASE[section] })}
        description={t(`${section}.body`)}
      />
    </Container>
  );
}
