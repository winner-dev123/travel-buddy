'use client';

import { useEffect, useRef, useState } from 'react';
import { useTranslations } from 'next-intl';
import { Button, Dialog, DialogContent } from '@travelbuddy/ui';

const IDLE_MS = 30 * 60 * 1000;
const WARN_MS = 2 * 60 * 1000;
const EVENTS = ['pointerdown', 'keydown', 'scroll', 'touchstart'] as const;

/**
 * Staff idle timeout (ADM-008). The platform enforces 30 min idle / 12 h absolute on admin routes
 * (`401 reauthentication_required`); this guard mirrors it in the UI: a warning two minutes before,
 * then a full reload into sign-in so no admin data stays on an unattended screen.
 */
export function AdminIdleGuard() {
  const t = useTranslations('admin.idle');
  const tc = useTranslations('common');
  const lastActivity = useRef(0);
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);

  useEffect(() => {
    lastActivity.current = Date.now();
    const bump = () => {
      lastActivity.current = Date.now();
    };
    for (const e of EVENTS) window.addEventListener(e, bump, { passive: true });
    const timer = window.setInterval(() => {
      const remaining = IDLE_MS - (Date.now() - lastActivity.current);
      if (remaining <= 0) {
        window.location.replace(`/login?reason=reauth&next=${encodeURIComponent(window.location.pathname)}`);
      } else if (remaining <= WARN_MS) {
        setSecondsLeft(Math.ceil(remaining / 1000));
      } else {
        setSecondsLeft(null);
      }
    }, 1000);
    return () => {
      for (const e of EVENTS) window.removeEventListener(e, bump);
      window.clearInterval(timer);
    };
  }, []);

  return (
    <Dialog
      open={secondsLeft !== null}
      onOpenChange={(open) => {
        if (!open) {
          lastActivity.current = Date.now();
          setSecondsLeft(null);
        }
      }}
    >
      <DialogContent title={t('title')} description={t('body', { seconds: secondsLeft ?? 0 })} closeLabel={tc('close')}>
        <Button
          onClick={() => {
            lastActivity.current = Date.now();
            setSecondsLeft(null);
          }}
        >
          {t('stay')}
        </Button>
      </DialogContent>
    </Dialog>
  );
}
