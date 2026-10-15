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
 * A cache that lies about money is worse than no cache at all.
 */
const CACHE = 'pulsar-shell-v1';
const SHELL = ['/', '/index.html', '/pulsar-logo.svg', '/favicon.svg', '/manifest.webmanifest'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting())
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
      .catch(() =>
        caches.match(event.request).then((cached) => cached || caches.match('/index.html'))
      )
  );
});
