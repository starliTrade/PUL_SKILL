/**
 * M44 — the Sentry SDK must not ship in the bundle when it is not configured.
 *
 * `monitoring.ts` used a top-level `import * as Sentry from "@sentry/react"`,
 * so the whole SDK (its largest single client dependency) was always bundled
 * and parsed even when `VITE_SENTRY_DSN` was unset — the default for every
 * deployment that has not set up monitoring. It must load lazily, only when a
 * DSN exists.
 *
 * The mock factory below records whether the module was ever imported. A
 * static import evaluates it at file load; a guarded dynamic import does not.
 */
import { describe, it, expect, vi } from 'vitest';

const sentry = vi.hoisted(() => ({
  imported: false,
  init: vi.fn(),
  captureException: vi.fn(),
  withScope: vi.fn(),
}));

vi.mock('@sentry/react', () => {
  sentry.imported = true;
  return {
    init: sentry.init,
    captureException: sentry.captureException,
    // Mirror Sentry's contract: run the callback with a scope object.
    withScope: (cb: (scope: { setContext: (key: string, value: unknown) => void }) => void) => {
      sentry.withScope(cb);
      cb({ setContext: () => {} });
    },
  };
});

import { initErrorMonitoring, reportError, errorMonitoringEnabled } from './monitoring';

describe('lazy Sentry (audit M44)', () => {
  it('never imports the SDK when no DSN is configured', async () => {
    // A static import would already have evaluated the mock at file load.
    expect(sentry.imported).toBe(false);

    await initErrorMonitoring();

    expect(sentry.imported).toBe(false);
    expect(sentry.init).not.toHaveBeenCalled();
    expect(errorMonitoringEnabled()).toBe(false);
  });

  it('reportError is a no-op before the SDK is loaded', () => {
    reportError(new Error('boom'), { where: 'test' });
    expect(sentry.captureException).not.toHaveBeenCalled();
  });

  it('loads and initialises the SDK when a DSN IS configured', async () => {
    vi.resetModules();
    const mod = await import('./monitoring');
    await mod.initErrorMonitoring('https://public@example.ingest.sentry.io/1');

    expect(sentry.imported).toBe(true);
    expect(sentry.init).toHaveBeenCalledTimes(1);

    mod.reportError(new Error('boom'), { where: 'test' });
    expect(sentry.captureException).toHaveBeenCalledTimes(1);
    expect(mod.errorMonitoringEnabled()).toBe(true);
  });
});
