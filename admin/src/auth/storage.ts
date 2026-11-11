/**
 * Browser storage that never throws (private windows and blocked storage just forget).
 *
 * - sessionStorage (this tab only, gone when it closes): the platform refresh token and the
 *   work reason. Access tokens stay in memory.
 * - localStorage: a random device ID for the session list and the chosen language. Nothing
 *   personal or secret.
 */

function store(kind: 'session' | 'local'): Storage | null {
  try {
    return kind === 'session' ? window.sessionStorage : window.localStorage;
  } catch {
    return null;
  }
}

export function readItem(kind: 'session' | 'local', key: string): string | null {
  try {
    return store(kind)?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

export function writeItem(kind: 'session' | 'local', key: string, value: string | null): void {
  try {
    const target = store(kind);
    if (!target) return;
    if (value === null) target.removeItem(key);
    else target.setItem(key, value);
  } catch {
    // Storage full or blocked: the console keeps working, it just won't remember.
  }
}

export const KEYS = {
  session: 'tb-staff-session',
  reason: 'tb-staff-reason',
  device: 'tb-staff-device',
  locale: 'tb-staff-locale',
  theme: 'tb-staff-theme',
} as const;

export function deviceId(): string {
  const existing = readItem('local', KEYS.device);
  if (existing && existing.length >= 8) return existing;
  const created = `staff-console-${crypto.randomUUID()}`;
  writeItem('local', KEYS.device, created);
  return created;
}
