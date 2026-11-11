#!/usr/bin/env node
/**
 * Deploy admin/dist to a Firebase Hosting site through the Hosting REST API (no firebase-tools).
 *
 *   FIREBASE_ACCESS_TOKEN=$(gcloud auth print-access-token) \
 *     node scripts/deploy-hosting.mjs --project travel-buddy-tb --site travel-buddy-admin \
 *       --api https://api-production-9dfc555a.up.railway.app [--create-site] [--dry-run]
 *
 * The token needs Firebase Hosting Admin on the project. The site gets a strict Content Security
 * Policy whose connect-src allows only the API and Firebase Authentication, and is never indexed.
 */
import { createHash } from 'node:crypto';
import { readdir, readFile } from 'node:fs/promises';
import { join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

const HOSTING = 'https://firebasehosting.googleapis.com/v1beta1';

function args() {
  const out = { createSite: false, dryRun: false };
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i += 1) {
    const name = argv[i];
    if (name === '--create-site') out.createSite = true;
    else if (name === '--dry-run') out.dryRun = true;
    else if (name.startsWith('--')) out[name.slice(2)] = argv[(i += 1)];
  }
  for (const required of ['project', 'site', 'api']) {
    if (!out[required]) throw new Error(`--${required} is required`);
  }
  if (!/^https:\/\/[^/]+$/.test(out.api)) throw new Error('--api must be an https origin without a path');
  return out;
}

export function hostingConfig(apiOrigin) {
  const csp = [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self'",
    "img-src 'self' data:",
    "font-src 'self'",
    `connect-src 'self' ${apiOrigin} https://identitytoolkit.googleapis.com`,
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "object-src 'none'",
    'upgrade-insecure-requests',
  ].join('; ');
  const security = {
    'Content-Security-Policy': csp,
    'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'no-referrer',
    'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=(), usb=()',
    'Cross-Origin-Opener-Policy': 'same-origin',
    'Cross-Origin-Resource-Policy': 'same-origin',
    'X-Robots-Tag': 'noindex, nofollow',
  };
  return {
    headers: [
      { glob: '**', headers: { ...security, 'Cache-Control': 'no-cache' } },
      { glob: '/assets/**', headers: { 'Cache-Control': 'public, max-age=31536000, immutable' } },
      { glob: '/fonts/**', headers: { 'Cache-Control': 'public, max-age=2592000' } },
    ],
    rewrites: [{ glob: '**', path: '/index.html' }],
    cleanUrls: false,
    trailingSlashBehavior: 'REMOVE',
  };
}

async function files(root) {
  const found = [];
  async function walk(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) await walk(path);
      else found.push(path);
    }
  }
  await walk(root);
  return Promise.all(
    found.map(async (path) => {
      const gz = gzipSync(await readFile(path), { level: 9 });
      return {
        url: `/${relative(root, path).split(sep).join('/')}`,
        gz,
        hash: createHash('sha256').update(gz).digest('hex'),
      };
    }),
  );
}

async function main() {
  const opts = args();
  const token = process.env.FIREBASE_ACCESS_TOKEN;
  if (!token) throw new Error('FIREBASE_ACCESS_TOKEN is not set');
  const headers = {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
    'x-goog-user-project': opts.project,
  };
  const call = async (method, url, body) => {
    const response = await fetch(url, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    const text = await response.text();
    if (!response.ok) throw new Error(`${method} ${url.replace(HOSTING, '')} -> ${response.status} ${text.slice(0, 400)}`);
    return text ? JSON.parse(text) : {};
  };

  const dist = fileURLToPath(new URL('../dist', import.meta.url));
  const bundle = await files(dist);
  if (!bundle.some((f) => f.url === '/index.html')) throw new Error('dist/index.html is missing: run npm run build');
  const config = hostingConfig(opts.api);
  console.log(`${bundle.length} files for https://${opts.site}.web.app (API ${opts.api})`);
  if (opts.dryRun) {
    console.log(JSON.stringify(config, null, 2));
    return;
  }

  if (opts.createSite) {
    try {
      await call('POST', `${HOSTING}/projects/${opts.project}/sites?siteId=${opts.site}`, {});
      console.log(`created site ${opts.site}`);
    } catch (error) {
      if (!String(error).includes('409')) throw error;
      console.log(`site ${opts.site} already exists`);
    }
  }

  const version = await call('POST', `${HOSTING}/sites/${opts.site}/versions`, { config });
  const populated = await call('POST', `${HOSTING}/${version.name}:populateFiles`, {
    files: Object.fromEntries(bundle.map((f) => [f.url, f.hash])),
  });
  const needed = new Set(populated.uploadRequiredHashes ?? []);
  for (const file of bundle.filter((f) => needed.has(f.hash))) {
    const response = await fetch(`${populated.uploadUrl}/${file.hash}`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/octet-stream' },
      body: file.gz,
    });
    if (!response.ok) throw new Error(`upload ${file.url} -> ${response.status}`);
  }
  console.log(`uploaded ${needed.size} new files`);
  await call('PATCH', `${HOSTING}/${version.name}?update_mask=status`, { status: 'FINALIZED' });
  const release = await call('POST', `${HOSTING}/sites/${opts.site}/releases?versionName=${version.name}`, {
    message: `staff console ${new Date().toISOString()}`,
  });
  console.log(`released ${release.name}`);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  main().catch((error) => {
    console.error(String(error.message ?? error));
    process.exit(1);
  });
}
