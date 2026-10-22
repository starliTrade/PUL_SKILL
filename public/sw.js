/*
 * PULSAR service worker (plan item 11.3 / G15).
 *
 * The one decision that matters here is what this must NOT cache.
 *
 * PULSAR settles real money. A service worker that caches API responses can show
 * a player a stale balance, a stale match, or a settlement that has already
 * happened — and "the app told me I had 5 USDT" is not an acceptable answer when
 * the chain says otherwise. So:
 *
 *   * `/api/*` is NEVER cached. Not network-first, not stale-while-revalidate:
 *     it goes to the network, and a failure is reported as a failure.
 *   * Only the static shell is cached, so the app opens offline and shows its own
 *     "you are offline" state instead of a browser error page.
 *
 * Audit M-18 (2026-10-22) — the cache name used to be the constant
 * 'pulsar-shell-v1' and install called `skipWaiting()` unconditionally. After a
 * deploy, a tab that was already open kept running the OLD chunks while the new
 * worker took over and deleted the old cache: the next navigation asked for a
 * hashed asset that no longer existed, got the cached index.html instead, and the
 * page was blank. Two changes:
 *
 *   1. CACHE is versioned from VERSION (kept equal to package.json by
 *      scripts/sync-sw-version.mjs, verified by a test). A new build is a new
 *      cache, so nothing is deleted under a live page's feet.
 *   2. install does NOT skipWaiting. The new worker waits until the page asks for
 *      it (`{type:'SKIP_WAITING'}`), which the app does after showing the player an
 *      "update available" prompt. The player decides when the reload happens —
 *      never mid-duel.
 */
const VERSION = '0.9.0';
const CACHE = `pulsar-shell-${VERSION}`;
const SHELL = ['/', '/index.html', '/pulsar-logo.svg', '/favicon.svg', '/manifest.webmanifest'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(SHELL))
    // NO skipWaiting: the old page keeps its own cache until the player updates.
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// The page asks for the swap only after telling the player (audit M-18).
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // NEVER cache the API. A stale balance is a lie about money.
  if (url.pathname.startsWith('/api/')) return;

  // Only GETs are cacheable at all.
  if (event.request.method !== 'GET') return;

  // Same-origin shell: network first, cache as the offline fallback.
  if (url.origin !== self.location.origin) return;

  event.respondWith(
    fetch(event.request)
      .then((response) => {
        // Only cache a real success. Caching an error page would make the
        // offline experience worse than having none.
        if (response.ok && response.type === 'basic') {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(event.request, copy));
        }
        return response;
      })
      .catch(async () => {
        const cached = await caches.match(event.request);
        if (cached) return cached;
        // A navigation to a path that is not cached still gets the shell.
        if (event.request.mode === 'navigate') {
          const shell = await caches.match('/index.html');
          if (shell) return shell;
        }
        return Response.error();
      })
  );
});
