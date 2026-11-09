import 'server-only';
import packageJson from '../../package.json';
import { publicApi } from './platform';

/**
 * Used only if the platform's client-config is momentarily unreachable. If it is stale, the
 * platform answers `403 consent_required` and the user is asked to review the updated terms;
 * the web never auto-accepts a version the user did not see.
 */
const FALLBACK = { terms: '2026-11-01', privacy: '2026-11-01' };

export interface LegalVersions {
  terms: string;
  privacy: string;
}

/** The web app's own version, sent as `app_version` to client-config (required, x.y.z). */
export const WEB_APP_VERSION: string = packageJson.version;

/**
 * Current legal document versions from `GET /v1/client-config?platform=web&app_version=` →
 * `legal` (contract ClientConfig). Registration must consent to exactly these.
 */
export async function getLegalVersions(locale = 'en'): Promise<LegalVersions> {
  try {
    const api = await publicApi(locale);
    const config = await api.config.get({ platform: 'web', app_version: WEB_APP_VERSION }, { revalidate: 300, tags: ['client-config'] });
    return { terms: config.legal.terms_version, privacy: config.legal.privacy_version };
  } catch {
    return FALLBACK;
  }
}
