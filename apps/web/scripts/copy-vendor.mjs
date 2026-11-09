// Copies browser assets that must be served as standalone files (not bundled) into public/vendor.
// MapLibre GL JS spawns its tile worker from a URL; bundlers rewrite that URL incorrectly, so the
// worker is served from /vendor/maplibre/ and configured with `setWorkerUrl` (ADR-0014).
import { copyFileSync, mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));
const maplibreDist = dirname(require.resolve('maplibre-gl/package.json'));
const target = join(here, '..', 'public', 'vendor', 'maplibre');

mkdirSync(target, { recursive: true });
copyFileSync(join(maplibreDist, 'dist', 'maplibre-gl-worker.mjs'), join(target, 'maplibre-gl-worker.mjs'));
console.log(`copied maplibre worker → ${target}`);
