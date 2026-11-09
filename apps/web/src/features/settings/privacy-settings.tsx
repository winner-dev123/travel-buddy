'use client';

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useTranslations } from 'next-intl';
import type { PrivacySettings } from '@travelbuddy/domain-types';
import { Alert, Card, NativeSelect, Switch } from '@travelbuddy/ui';
import { setFeedLocationPreference, useFeedLocationPreference } from '@/features/feed/location-preference';
import { browserApi } from '@/lib/api-browser';

/** Privacy controls (brief §15, §23). Every change is saved to the platform immediately. */
export function PrivacySettingsForm({ initial }: { initial: PrivacySettings }) {
  const t = useTranslations('settings.privacy');
  const [privacy, setPrivacy] = useState(initial);
  const feedLocation = useFeedLocationPreference();

  const save = useMutation({
    mutationFn: (patch: Partial<PrivacySettings>) => browserApi().me.updatePrivacy(patch),
    onMutate: (patch) => {
      const previous = privacy;
      setPrivacy((p) => ({ ...p, ...patch }));
      return previous;
    },
    onError: (_e, _p, previous) => previous && setPrivacy(previous),
    onSuccess: (server) => setPrivacy(server),
  });

  return (
    <Card className="flex flex-col divide-y divide-border">
      <Row id="discovery" title={t('discovery')} hint={t('discoveryHint')}>
        <Switch id="discovery" checked={privacy.discovery_enabled} onCheckedChange={(v) => save.mutate({ discovery_enabled: v })} />
      </Row>
      <Row id="granularity" title={t('granularity')} hint={t('granularityHint')}>
        <NativeSelect id="granularity" className="h-9 w-auto" value={privacy.discovery_granularity} onChange={(e) => save.mutate({ discovery_granularity: e.target.value as PrivacySettings['discovery_granularity'] })}>
          <option value="city">{t('city')}</option>
          <option value="neighborhood">{t('neighborhood')}</option>
        </NativeSelect>
      </Row>
      <Row id="profile-visibility" title={t('profileVisibility')} hint={t('profileVisibilityHint')}>
        <NativeSelect id="profile-visibility" className="h-9 w-auto" value={privacy.profile_visibility} onChange={(e) => save.mutate({ profile_visibility: e.target.value as PrivacySettings['profile_visibility'] })}>
          <option value="public">{t('public')}</option>
          <option value="connections">{t('connections')}</option>
        </NativeSelect>
      </Row>
      <Row id="requests" title={t('requests')} hint={t('requestsHint')}>
        <NativeSelect id="requests" className="h-9 w-auto" value={privacy.connection_requests_from} onChange={(e) => save.mutate({ connection_requests_from: e.target.value as PrivacySettings['connection_requests_from'] })}>
          <option value="everyone">{t('everyone')}</option>
          <option value="shared_context">{t('sharedContext')}</option>
          <option value="nobody">{t('nobody')}</option>
        </NativeSelect>
      </Row>
      <Row id="search-indexing" title={t('searchIndexing')} hint={t('searchIndexingHint')}>
        <Switch
          id="search-indexing"
          checked={privacy.search_engine_indexing === true}
          onCheckedChange={(v) => save.mutate({ search_engine_indexing: v })}
        />
      </Row>
      <Row id="feed-location" title={t('feedLocation')} hint={t('feedLocationHint')}>
        <Switch
          id="feed-location"
          checked={feedLocation}
          onCheckedChange={setFeedLocationPreference}
        />
      </Row>
      {save.isError ? (
        <div className="p-4">
          <Alert tone="danger">{t('error')}</Alert>
        </div>
      ) : null}
    </Card>
  );
}

function Row({ id, title, hint, children }: { id: string; title: string; hint: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 p-4">
      <label htmlFor={id} className="flex flex-col">
        <span className="font-semibold">{title}</span>
        <span className="text-sm text-muted-foreground">{hint}</span>
      </label>
      {children}
    </div>
  );
}
