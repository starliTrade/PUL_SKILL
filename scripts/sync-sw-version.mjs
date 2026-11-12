#!/usr/bin/env node
/**
 * Audit M-18 — keep the service worker's cache name tied to the build.
 *
 * A cache name that nobody bumps is a cache that never invalidates; a cache name
 * that is bumped by hand is a cache that is forgotten on the release that
 * matters. This writes package.json's `version` into public/sw.js so the version
 * has exactly one source of truth. Run by `prebuild`, and by `postversion` so a
 * `npm version` commit carries the synced worker with it.
 *
 * The test `src/test/pwa.service-worker.test.ts` fails when the two drift, so a
 * forgotten run is loud rather than silent.
 */
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const pkg = JSON.parse(readFileSync(resolve(root, 'package.json'), 'utf8'));
const swPath = resolve(root, 'public/sw.js');
const source = readFileSync(swPath, 'utf8');

const version = String(pkg.version || '0.0.0');
const PATTERN = /^const VERSION = '[^']*';$/m;
if (!PATTERN.test(source)) {
  console.error(
    "[sync-sw-version] could not find the `const VERSION = '...';` line in public/sw.js",
  );
  process.exit(1);
}
// NOTE: compare with a matcher, not `next === source` — when the version is
// already correct the two strings are equal and that check reports a failure.
const next = source.replace(PATTERN, `const VERSION = '${version}';`);
writeFileSync(swPath, next);
console.log(`[sync-sw-version] public/sw.js cache version = ${version}`);
