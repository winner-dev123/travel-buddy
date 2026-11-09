'use client';

import { useState } from 'react';
import { useTranslations } from 'next-intl';
import { REPORT_REASONS, type ReportReason, type ReportTargetType } from '@travelbuddy/domain-types';
import { Alert, Button, Dialog, DialogContent, FormField, Textarea } from '@travelbuddy/ui';
import { browserApi } from '@/lib/api-browser';

/** Report flow (brief §10, §29). Optionally blocks the author in the same step (contract `also_block`). */
export function ReportDialog({
  open,
  onOpenChange,
  targetType,
  targetId,
  onBlocked,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  targetType: ReportTargetType;
  targetId: string;
  onBlocked?: () => void;
}) {
  const t = useTranslations('report');
  const tc = useTranslations('common');
  const [reason, setReason] = useState<ReportReason | null>(null);
  const [details, setDetails] = useState('');
  const [alsoBlock, setAlsoBlock] = useState(false);
  const [state, setState] = useState<'idle' | 'sending' | 'done' | 'error'>('idle');

  const submit = async () => {
    if (!reason) return;
    setState('sending');
    try {
      await browserApi().reports.create({ target_type: targetType, target_id: targetId, reason, details: details.trim() || undefined, also_block: alsoBlock || undefined });
      setState('done');
      if (alsoBlock) onBlocked?.();
    } catch {
      setState('error');
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        onOpenChange(o);
        if (!o) {
          setReason(null);
          setDetails('');
          setAlsoBlock(false);
          setState('idle');
        }
      }}
    >
      <DialogContent title={t('title')} description={t('description')} closeLabel={tc('close')}>
        {state === 'done' ? (
          <Alert tone="success" title={t('thanksTitle')}>
            {t('thanksBody')}
          </Alert>
        ) : (
          <div className="flex flex-col gap-4">
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-2 text-sm font-semibold">{t('reasonLabel')}</legend>
              {REPORT_REASONS.map((r) => (
                <label key={r} className="flex cursor-pointer items-center gap-3 rounded-xl border border-border px-3 py-2 text-sm has-[:checked]:border-primary has-[:checked]:bg-primary-soft">
                  <input type="radio" name="reason" value={r} checked={reason === r} onChange={() => setReason(r)} className="accent-[var(--tb-primary)]" />
                  {t(`reasons.${r}`)}
                </label>
              ))}
            </fieldset>
            <FormField id="report-details" label={t('detailsLabel')} hint={t('detailsHint')}>
              <Textarea value={details} maxLength={1000} onChange={(e) => setDetails(e.target.value)} />
            </FormField>
            <label className="flex items-center gap-3 text-sm">
              <input type="checkbox" checked={alsoBlock} onChange={(e) => setAlsoBlock(e.target.checked)} className="size-4 accent-[var(--tb-primary)]" />
              {t('alsoBlock')}
            </label>
            {state === 'error' ? <Alert tone="danger">{t('error')}</Alert> : null}
            <Button onClick={submit} disabled={!reason} loading={state === 'sending'}>
              {t('submit')}
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
