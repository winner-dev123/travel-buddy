import { Link } from 'react-router';

import { useI18n } from '../i18n/I18n';

export function NotFoundPage() {
  const { t } = useI18n();
  return (
    <div className="stack">
      <h1>{t('notFound.title')}</h1>
      <Link to="/">{t('notFound.home')}</Link>
    </div>
  );
}
