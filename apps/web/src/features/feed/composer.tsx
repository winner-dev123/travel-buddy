'use client';

import { useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useFormatter, useNow, useTranslations } from 'next-intl';
import { ImagePlus, MapPin, X } from 'lucide-react';
import { isApiError, newIdempotencyKey } from '@travelbuddy/api-client';
import { LOCATED_POST_KINDS, POST_VISIBILITIES, type PostKind } from '@travelbuddy/domain-types';
import { createPostSchema, LIMITS } from '@travelbuddy/validation';
import { Alert, Avatar, Button, Dialog, DialogContent, FormField, NativeSelect, Textarea } from '@travelbuddy/ui';
import { DestinationSearch } from '@/components/destination-search';
import { useViewer } from '@/features/shell/viewer-context';
import { browserApi } from '@/lib/api-browser';
import { qk } from '@/lib/query-keys';
import { useComposerStore } from './composer-store';

const KINDS = ['experience', 'tip', 'attraction_recommendation', 'restaurant_recommendation'] as const satisfies readonly PostKind[];

/**
 * Post composer (brief §11). Drafts persist per browser. Visibility defaults to followers; Public is
 * never preselected silently. Precise GPS is never attached — only a chosen destination.
 * Photo/video uploads need the platform media pipeline and are disabled until it exists.
 */
export function Composer({ defaultDestination }: { defaultDestination?: { id: string; name: string; path: string } | null }) {
  const t = useTranslations('composer');
  const tc = useTranslations('common');
  const tp = useTranslations('post');
  const viewer = useViewer();
  const queryClient = useQueryClient();
  const draft = useComposerStore();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const destination = draft.destination === undefined ? (defaultDestination ?? null) : draft.destination;
  const needsLocation = !destination && (LOCATED_POST_KINDS as readonly string[]).includes(draft.kind);
  // One Idempotency-Key per draft content: retrying after a timeout replays instead of posting twice,
  // while an edited draft gets a fresh key (the platform answers 409 for a reused key with a new body).
  const attempt = useRef<{ fingerprint: string; key: string } | null>(null);
  const format = useFormatter();
  const now = useNow({ updateInterval: 60_000 });

  const publish = useMutation({
    mutationFn: async () => {
      const body = {
        kind: draft.kind,
        body: draft.body.trim(),
        visibility: draft.visibility,
        location_precision: destination ? ('destination' as const) : ('none' as const),
        ...(destination ? { destination_id: destination.id } : {}),
      };
      const parsed = createPostSchema.safeParse(body);
      if (!parsed.success) throw new Error('invalid');
      const fingerprint = JSON.stringify(parsed.data);
      if (attempt.current?.fingerprint !== fingerprint) attempt.current = { fingerprint, key: newIdempotencyKey() };
      return browserApi().posts.create(parsed.data, attempt.current.key);
    },
    onSuccess: () => {
      attempt.current = null;
      draft.reset();
      setOpen(false);
      void queryClient.invalidateQueries({ queryKey: qk.feedAll() });
    },
    onError: (e) => setError(isApiError(e) && e.requestId ? t('errorRef', { id: e.requestId }) : t('error')),
  });

  // SAFE-013: explain moderation limits up front instead of failing on submit (all hooks above).
  const postingLimit = viewer.restrictions.find(
    (r) => r.kind === 'posting_limited' && (r.until === null || new Date(r.until).getTime() > now.getTime()),
  );
  if (postingLimit) {
    return (
      <Alert tone="warning">
        {postingLimit.until
          ? t('restricted', { date: format.dateTime(new Date(postingLimit.until), { dateStyle: 'medium', timeStyle: 'short' }) })
          : t('restrictedIndefinite')}
      </Alert>
    );
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex w-full items-center gap-3 rounded-card border border-border bg-surface p-4 text-start shadow-card transition-colors hover:border-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Avatar name={viewer.displayName} size={40} />
        <span className="flex-1 text-muted-foreground">{draft.body ? t('continueDraft') : t('prompt')}</span>
      </button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent title={t('title')} closeLabel={tc('close')}>
          <div className="flex flex-col gap-4">
            <FormField id="composer-body" label={t('bodyLabel')} hint={t('counter', { count: draft.body.length, max: LIMITS.postBody.max })}>
              <Textarea value={draft.body} maxLength={LIMITS.postBody.max} rows={5} onChange={(e) => draft.setBody(e.target.value)} placeholder={t('placeholder')} />
            </FormField>

            <div className="flex flex-col gap-2">
              <span className="text-sm font-semibold">{t('destinationLabel')}</span>
              {destination ? (
                <span className="flex items-center justify-between rounded-xl border border-border px-3 py-2 text-sm">
                  <span className="flex items-center gap-2">
                    <MapPin className="size-4 text-primary" aria-hidden="true" />
                    {destination.name}
                  </span>
                  <button type="button" onClick={() => draft.setDestination(null)} aria-label={t('removeDestination')} className="rounded-full p-1 hover:bg-surface-muted">
                    <X className="size-4" aria-hidden="true" />
                  </button>
                </span>
              ) : (
                <DestinationSearch size="md" label={t('destinationLabel')} onSelect={(d) => draft.setDestination({ id: d.id, name: d.name, path: d.path })} />
              )}
              {needsLocation ? (
                <p id="composer-destination-required" className="text-xs font-medium text-warning">
                  {t('destinationRequired')}
                </p>
              ) : null}
              <p className="text-xs text-muted-foreground">{t('noGps')}</p>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <FormField id="composer-kind" label={t('kindLabel')}>
                <NativeSelect value={draft.kind} onChange={(e) => draft.setKind(e.target.value as PostKind)}>
                  {KINDS.map((k) => (
                    <option key={k} value={k}>
                      {t(`kinds.${k}`)}
                    </option>
                  ))}
                </NativeSelect>
              </FormField>
              <FormField id="composer-visibility" label={t('visibilityLabel')} hint={draft.visibility === 'public' ? t('publicHint') : undefined}>
                <NativeSelect value={draft.visibility} onChange={(e) => draft.setVisibility(e.target.value as (typeof POST_VISIBILITIES)[number])}>
                  {POST_VISIBILITIES.map((v) => (
                    <option key={v} value={v}>
                      {tp(`visibility.${v}`)}
                    </option>
                  ))}
                </NativeSelect>
              </FormField>
            </div>

            <Button type="button" variant="secondary" disabled title={t('mediaUnavailable')}>
              <ImagePlus aria-hidden="true" />
              {t('addMedia')}
            </Button>
            <p className="-mt-2 text-xs text-muted-foreground">{t('mediaUnavailable')}</p>

            {error ? <Alert tone="danger">{error}</Alert> : null}
            <div className="flex justify-between gap-2">
              <Button type="button" variant="ghost" onClick={() => draft.reset()} disabled={!draft.body}>
                {t('discard')}
              </Button>
              <Button
                type="button"
                onClick={() => publish.mutate()}
                loading={publish.isPending}
                disabled={!draft.body.trim() || needsLocation}
                aria-describedby={needsLocation ? 'composer-destination-required' : undefined}
              >
                {t('publish')}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
