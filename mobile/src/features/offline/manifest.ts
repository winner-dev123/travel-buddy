import { ed25519 } from '@noble/curves/ed25519';

/** Contract `OfflineManifest` (server-signed, ADR-0026). */
export interface OfflineManifest {
  package_id: string;
  destination_id: string;
  kind: 'guide' | 'audio_tour' | 'map_region' | 'bundle';
  locale: string;
  version: number;
  files: { path: string; bytes: number; sha256: string; content_type: string }[];
  total_bytes: number;
  sha256: string;
  min_app_version: string;
  content_license: string;
  license_expires_at: string | null;
  issued_at: string;
  signature_alg: 'Ed25519';
  key_id: string;
  signature: string;
}

export interface ManifestKey {
  key_id: string;
  alg: 'Ed25519';
  public_key: string;
}

/**
 * The bytes the server signs: JSON with keys sorted at every level and no whitespace, UTF-8
 * (Python's `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`).
 */
export function canonicalJson(value: unknown): string {
  if (value === null || typeof value !== 'object') {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(',')}]`;
  }
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, item]) => item !== undefined)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
  return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonicalJson(item)}`).join(',')}}`;
}

function base64Bytes(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

/** True when the manifest was signed by one of the published keys (matched by `key_id`). */
export function verifyManifest(manifest: OfflineManifest, keys: readonly ManifestKey[]): boolean {
  const key = keys.find((candidate) => candidate.key_id === manifest.key_id);
  if (!key || manifest.signature_alg !== 'Ed25519') {
    return false;
  }
  const { signature, ...unsigned } = manifest;
  try {
    return ed25519.verify(
      base64Bytes(signature),
      new TextEncoder().encode(canonicalJson(unsigned)),
      base64Bytes(key.public_key),
    );
  } catch {
    return false;
  }
}
