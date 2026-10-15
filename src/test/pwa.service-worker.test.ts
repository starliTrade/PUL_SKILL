/**
 * The PWA service worker (plan item 11.3 / G15).
 *
 * The property that matters is what it must NOT cache. PULSAR settles real
 * money, so a service worker that caches API responses can show a player a stale
 * balance or a settlement that already happened — and "the app told me I had
 * 5 USDT" is not an acceptable answer when the chain says otherwise.
 *
 * So this does not read the file and look for strings. It LOADS the worker with
 * a fake worker scope and drives its fetch handler, because "the code contains
 * `/api/`" and "an /api/ request is not intercepted" are different claims.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

type Handler = (event: { request: Request; respondWith: (r: unknown) => void }) => void;

function loadWorker() {
  const source = readFileSync(resolve(__dirname, '../../public/sw.js'), 'utf8');
  const handlers: Record<string, Handler> = {};
  const cachePut = vi.fn();
  const scope = {
    addEventListener: (type: string, fn: Handler) => {
      handlers[type] = fn;
    },
    skipWaiting: vi.fn(),
    clients: { claim: vi.fn() },
    location: { origin: 'https://pulsar.test' },
  };
  const caches = {
    open: vi.fn(async () => ({ addAll: vi.fn(), put: cachePut })),
    keys: vi.fn(async () => []),
    delete: vi.fn(),
    match: vi.fn(async () => undefined),
  };
  // `fetch` must return a promise: the worker chains `.then`/`.catch` on it, and
  // a bare `vi.fn()` makes the shell path throw instead of exercising it.
  const fetchFn = vi.fn(async () => new Response('ok', { status: 200 }));
  new Function('self', 'caches', 'fetch', source)(scope, caches, fetchFn);
  return { handlers, cachePut };
}

describe('the service worker never caches money', () => {
  let worker: ReturnType<typeof loadWorker>;

  beforeEach(() => {
    worker = loadWorker();
  });

  it('registers install, activate and fetch handlers', () => {
    expect(Object.keys(worker.handlers).sort()).toEqual(['activate', 'fetch', 'install']);
  });

  it('does NOT intercept /api/ requests', () => {
    const respondWith = vi.fn();
    worker.handlers.fetch({
      request: new Request('https://pulsar.test/api/health'),
      respondWith,
    });
    expect(respondWith).not.toHaveBeenCalled();
  });

  it('does not intercept ANY /api/ path, including the money ones', () => {
    for (const path of ['/api/queue', '/api/round/commit', '/api/match/x/settle', '/api/eligibility']) {
      const respondWith = vi.fn();
      worker.handlers.fetch({ request: new Request(`https://pulsar.test${path}`), respondWith });
      expect(respondWith, `${path} must not be served from cache`).not.toHaveBeenCalled();
    }
  });

  it('DOES intercept the static shell, so the app opens offline', () => {
    const respondWith = vi.fn();
    worker.handlers.fetch({ request: new Request('https://pulsar.test/'), respondWith });
    expect(respondWith).toHaveBeenCalled();
  });

  it('does not intercept non-GET requests', () => {
    const respondWith = vi.fn();
    worker.handlers.fetch({
      request: new Request('https://pulsar.test/', { method: 'POST' }),
      respondWith,
    });
    expect(respondWith).not.toHaveBeenCalled();
  });

  it('does not intercept cross-origin requests', () => {
    const respondWith = vi.fn();
    worker.handlers.fetch({ request: new Request('https://elsewhere.test/x'), respondWith });
    expect(respondWith).not.toHaveBeenCalled();
  });
});
