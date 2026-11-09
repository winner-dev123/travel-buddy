function fnv1a(input: string, seed: number): number {
  let hash = seed >>> 0;
  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash >>> 0;
}

function formatUuid(hex: string): string {
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20, 32)}`;
}

/**
 * Deterministic UUID (version 7 layout, RFC 9562 variant) derived from a fixture key, so seeded
 * URLs such as `/stories/{id}` stay stable across dev-server restarts.
 */
export function fixtureId(key: string): string {
  const hex = [0x811c9dc5, 0x2c1b3c6d, 0x297a2d39, 0x5bd1e995]
    .map((seed) => fnv1a(key, seed).toString(16).padStart(8, '0'))
    .join('')
    .split('');
  hex[12] = '7';
  hex[16] = ((parseInt(hex[16] ?? '0', 16) & 0x3) | 0x8).toString(16);
  return formatUuid(hex.join(''));
}

/** Time-ordered UUIDv7 for records created at runtime. */
export function uuidv7(now: number = Date.now()): string {
  const bytes = new Uint8Array(16);
  globalThis.crypto.getRandomValues(bytes);
  let ts = now;
  for (let i = 5; i >= 0; i--) {
    bytes[i] = ts % 256;
    ts = Math.floor(ts / 256);
  }
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x70;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  return formatUuid(Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join(''));
}

export function randomToken(prefix: string): string {
  const bytes = new Uint8Array(32);
  globalThis.crypto.getRandomValues(bytes);
  let binary = '';
  for (const b of bytes) binary += String.fromCharCode(b);
  return `${prefix}_${btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')}`;
}
