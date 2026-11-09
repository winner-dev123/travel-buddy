import 'server-only';
import { publicApi } from './platform';

/** Used only if the platform's client-config is unavailable (matches the platform's current values). */
const FALLBACK = { terms: '2026-11-01', privacy: '2026-11-01' };

export interface LegalVersions {
  terms: string;
  privacy: string;
}

/**
 * Current legal document versions from `GET /v1/client-config` → `legal` (contract ClientConfig).
 * Registration must consent to exactly these; the platform answers `403 consent_required` otherwise.
 */
export async function getLegalVersions(locale = 'en'): Promise<LegalVersions> {
  try {
    const api = await publicApi(locale);
    const config = await api.config.get({ revalidate: 300, tags: ['client-config'] });
    return { terms: config.legal.terms_version, privacy: config.legal.privacy_version };
  } catch {
    return FALLBACK;
  }
}
