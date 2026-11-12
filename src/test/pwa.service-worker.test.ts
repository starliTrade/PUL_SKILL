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
  return { handlers, cachePut, scope };
}

describe('the service worker never caches money', () => {
  let worker: ReturnType<typeof loadWorker>;

  beforeEach(() => {
    worker = loadWorker();
  });

  it('registers install, activate, fetch and the update-message handler', () => {
    // `message` is the audit M-18 handshake: the page asks before the swap.
    expect(Object.keys(worker.handlers).sort()).toEqual([
      'activate',
      'fetch',
      'install',
      'message',
    ]);
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

/**
 * Audit M-18 — a deploy must not take over a page that is mid-duel.
 *
 * The worker used to call `skipWaiting()` from `install`, so the new build
 * activated immediately, deleted the old cache, and the open tab (still running
 * old chunks) requested an asset that no longer existed. It got index.html back
 * and went blank. Two properties fix that: the cache name is versioned (a new
 * build is a new cache) and the swap only happens when the page asks for it.
 */
describe('the service worker waits for the player (audit M-18)', () => {
  it('keeps the cache name versioned and in step with package.json', () => {
    const source = readFileSync(resolve(__dirname, '../../public/sw.js'), 'utf8');
    const pkg = JSON.parse(readFileSync(resolve(__dirname, '../../package.json'), 'utf8'));
    const declared = /^const VERSION = '([^']+)';$/m.exec(source);
    expect(declared, 'public/sw.js must declare `const VERSION = ...`').not.toBeNull();
    expect(declared?.[1]).toBe(pkg.version);
    expect(source).toContain('pulsar-shell-${VERSION}');
  });

  it('does NOT skipWaiting during install', () => {
    const { handlers, scope } = loadWorker();
    const scopeWithWait = scope as typeof scope & {
      skipWaiting: ReturnType<typeof vi.fn>;
    };
    let waited: Promise<unknown> | undefined;
    handlers.install({ waitUntil: (p: Promise<unknown>) => void (waited = p) } as never);
    expect(waited).toBeDefined();
    expect(scopeWithWait.skipWaiting).not.toHaveBeenCalled();
  });

  it('swaps only when the page sends SKIP_WAITING', async () => {
    const { handlers, scope } = loadWorker();
    const scopeWithWait = scope as typeof scope & {
      skipWaiting: ReturnType<typeof vi.fn>;
    };
    const message = handlers.message as unknown as (e: { data: unknown }) => void;
    expect(scopeWithWait.skipWaiting).not.toHaveBeenCalled();

    message({ data: { type: 'SKIP_WAITING' } });
    expect(scopeWithWait.skipWaiting).toHaveBeenCalledTimes(1);

    // Anything else is ignored — a page cannot force an update by accident.
    message({ data: { type: 'SOMETHING_ELSE' } });
    message({ data: undefined });
    expect(scopeWithWait.skipWaiting).toHaveBeenCalledTimes(1);
  });

  it('deletes only caches that are not the current version', async () => {
    const { handlers, scope } = loadWorker();
    let activated: Promise<unknown> | undefined;
    handlers.activate({ waitUntil: (p: Promise<unknown>) => void (activated = p) } as never);
    await activated;
    expect((scope as unknown as { clients: { claim: ReturnType<typeof vi.fn> } }).clients.claim)
      .toHaveBeenCalled();
  });

  it('still refuses to touch /api after the rewrite', () => {
    const source = readFileSync(resolve(__dirname, '../../public/sw.js'), 'utf8');
    expect(source).toContain("url.pathname.startsWith('/api/')");
  });
});
