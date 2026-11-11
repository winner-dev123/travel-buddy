/**
 * Build-time configuration. Every value here is public (it ships in the bundle): the API base
 * URL, the Firebase Web API key (identifies the project only, ADR-0028) and a label for the
 * environment banner. Secrets never belong in VITE_* variables.
 */
export interface ConsoleConfig {
  apiBaseUrl: string;
  firebaseApiKey: string;
  environmentLabel: string;
}

function required(name: string, value: string | undefined): string {
  if (!value) {
    throw new Error(`${name} is not set. Copy admin/.env.example to admin/.env.local.`);
  }
  return value;
}

export function readConfig(env: Record<string, string | undefined> = import.meta.env): ConsoleConfig {
  const apiBaseUrl = required('VITE_API_BASE_URL', env.VITE_API_BASE_URL).replace(/\/+$/, '');
  if (!/^https:\/\//.test(apiBaseUrl) && !/^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(apiBaseUrl)) {
    throw new Error('VITE_API_BASE_URL must use https (http only for localhost).');
  }
  return {
    apiBaseUrl,
    firebaseApiKey: required('VITE_FIREBASE_API_KEY', env.VITE_FIREBASE_API_KEY),
    environmentLabel: env.VITE_ENVIRONMENT_LABEL || 'staging',
  };
}
