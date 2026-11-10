import * as Crypto from 'expo-crypto';
import { Directory, File, Paths } from 'expo-file-system';

import type { ApiClient } from '@/api';
import { APP_VERSION, clientPlatform, getDeviceId } from '@/auth/session';

import { verifyManifest, type ManifestKey, type OfflineManifest } from './manifest';

/** Contract `OfflinePackageSummary`. */
export interface OfflinePackageSummary {
  id: string;
  destination_id: string;
  locale: string;
  kind: OfflineManifest['kind'];
  version: number;
  total_bytes: number;
  tier: 'free' | 'premium' | 'purchasable';
  entitled: boolean;
  license_expires_at: string | null;
}

interface OfflineLicense {
  id: string;
  package_id: string;
  manifest: OfflineManifest;
  download: { base_url: string; expires_at: string };
  quota: { limit: number; used: number };
}

/** One downloaded package, as recorded on this device. */
export interface DownloadedPackage {
  package_id: string;
  license_id: string;
  kind: OfflineManifest['kind'];
  destination_id: string;
  destination_name: string;
  locale: string;
  version: number;
  total_bytes: number;
  files: string[];
  license_expires_at: string | null;
  downloaded_at: string;
}

export class OfflineIntegrityError extends Error {}

const root = () => new Directory(Paths.document, 'offline');
const indexFile = () => new File(root(), 'downloads.json');
const packageDir = (id: string) => new Directory(root(), id);

function expired(entry: { license_expires_at: string | null }, now = Date.now()): boolean {
  return entry.license_expires_at !== null && Date.parse(entry.license_expires_at) <= now;
}

/** Downloads on this device whose content license is still valid (OFF-005). */
export async function listDownloads(): Promise<DownloadedPackage[]> {
  const file = indexFile();
  if (!file.exists) {
    return [];
  }
  try {
    const entries = JSON.parse(await file.text()) as DownloadedPackage[];
    return entries.filter((entry) => !expired(entry));
  } catch {
    return [];
  }
}

async function saveIndex(entries: DownloadedPackage[]): Promise<void> {
  root().create({ intermediates: true, idempotent: true });
  await indexFile().write(JSON.stringify(entries));
}

export async function listPackages(
  client: ApiClient,
  destinationId: string,
): Promise<OfflinePackageSummary[]> {
  const result = await client.get<{ data: OfflinePackageSummary[] }>(
    `/v1/destinations/${destinationId}/offline-packages`,
  );
  return result.data;
}

async function manifestKeys(client: ApiClient): Promise<ManifestKey[]> {
  const config = await client.get<{ offline_manifest_keys?: ManifestKey[] }>('/v1/client-config', {
    query: { platform: clientPlatform(), app_version: APP_VERSION },
  });
  return config.offline_manifest_keys ?? [];
}

async function fetchVerified(url: string, sha256: string): Promise<string> {
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const response = await fetch(url);
    if (response.ok) {
      const text = await response.text();
      const digest = await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, text);
      if (digest === sha256) {
        return text;
      }
    }
  }
  throw new OfflineIntegrityError(`could not download ${url.split('/').pop()}`);
}

/**
 * License the package to this device, verify the signed manifest, then download every file and
 * check its SHA-256 (a corrupted file is fetched once more before giving up; OFF-001).
 */
export async function downloadPackage(
  client: ApiClient,
  pkg: OfflinePackageSummary,
  destinationName: string,
): Promise<DownloadedPackage> {
  const license = await client.post<OfflineLicense>(`/v1/offline-packages/${pkg.id}/licenses`, {
    body: { device_id: await getDeviceId() }, // licenses are per device (OFF-004)
  });
  if (!verifyManifest(license.manifest, await manifestKeys(client))) {
    throw new OfflineIntegrityError('the package manifest is not signed by Travel Buddy');
  }
  const target = packageDir(pkg.id);
  target.create({ intermediates: true, idempotent: true });
  for (const entry of license.manifest.files) {
    const text = await fetchVerified(`${license.download.base_url}${entry.path}`, entry.sha256);
    await new File(target, entry.path).write(text);
  }
  const downloaded: DownloadedPackage = {
    package_id: pkg.id,
    license_id: license.id,
    kind: pkg.kind,
    destination_id: pkg.destination_id,
    destination_name: destinationName,
    locale: pkg.locale,
    version: license.manifest.version,
    total_bytes: license.manifest.total_bytes,
    files: license.manifest.files.map((entry) => entry.path),
    license_expires_at: license.manifest.license_expires_at,
    downloaded_at: new Date().toISOString(),
  };
  // A newer version replaces the older copy (the server already released its license).
  const existing = await listDownloads();
  const replaced = existing.filter(
    (entry) =>
      entry.package_id !== pkg.id &&
      entry.destination_id === pkg.destination_id &&
      entry.locale === pkg.locale &&
      entry.kind === pkg.kind,
  );
  replaced.forEach((entry) => deletePackageFiles(entry.package_id));
  await saveIndex([
    ...existing.filter((entry) => !replaced.includes(entry) && entry.package_id !== pkg.id),
    downloaded,
  ]);
  return downloaded;
}

function deletePackageFiles(packageId: string): void {
  const dir = packageDir(packageId);
  if (dir.exists) {
    dir.delete();
  }
}

/** Remove a download and release its license (the release is retried by the next removal). */
export async function removeDownload(client: ApiClient, entry: DownloadedPackage): Promise<void> {
  deletePackageFiles(entry.package_id);
  await saveIndex((await listDownloads()).filter((item) => item.package_id !== entry.package_id));
  try {
    await client.delete(`/v1/offline-packages/${entry.package_id}/licenses/${entry.license_id}`);
  } catch {
    // Offline: the license stays counted until the next online removal or its expiry.
  }
}

/** A downloaded guide, read from the device (OFF-002: works in airplane mode). */
export async function offlineGuide<T>(guideId: string): Promise<T | null> {
  for (const entry of await listDownloads()) {
    const index = new File(packageDir(entry.package_id), 'index.json');
    if (!index.exists) {
      continue;
    }
    const contents = JSON.parse(await index.text()) as { guides: { id: string; file: string }[] };
    const match = contents.guides.find((guide) => guide.id === guideId);
    if (match) {
      const file = new File(packageDir(entry.package_id), match.file);
      return file.exists ? (JSON.parse(await file.text()) as T) : null;
    }
  }
  return null;
}
