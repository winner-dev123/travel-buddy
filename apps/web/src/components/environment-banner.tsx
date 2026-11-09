import { getTranslations } from 'next-intl/server';
import { FlaskConical } from 'lucide-react';

/** Persistent, unmissable notice that the UI is running on the mock adapter (docs/web/01 §7.1). */
export async function EnvironmentBanner() {
  const t = await getTranslations('env');
  return (
    <div
      role="note"
      className="relative z-40 flex items-center justify-center gap-2 bg-[#17252a] px-4 py-1.5 text-center text-xs font-medium text-white"
    >
      <FlaskConical className="size-3.5 shrink-0" aria-hidden="true" />
      <span>
        <strong className="font-semibold">{t('mockTitle')}</strong> · {t('mockDescription')}
      </span>
    </div>
  );
}
