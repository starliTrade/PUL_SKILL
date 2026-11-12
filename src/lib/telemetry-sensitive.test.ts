/**
 * Audit L-01 — the failures that matter must not exist only in the console.
 *
 * `realWeb3` caught several money- or data-relevant errors and printed them:
 * a failed balance read (the player may think their money moved), an
 * unreachable progression ledger (the UI then shows a local estimate), and a
 * dead settlement feed (the "recent duels" list goes stale). None of it reached
 * `monitoring.reportError`, so in production nobody could see how often any of
 * them happened — the only witness was the affected player's console.
 *
 * A behavioural test would need a faked RPC, a faked server and a Sentry stub;
 * the property under test is "these catch blocks report", so it is pinned at
 * the source, the same way the other honest-failure gates in this repo are.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const SOURCE = readFileSync(resolve(__dirname, './realWeb3.ts'), 'utf-8');

describe('sensitive client failures report to telemetry (audit L-01)', () => {
  it('imports the reporter', () => {
    expect(SOURCE).toContain("import { reportError } from './monitoring'");
  });

  for (const area of ['balance', 'progression', 'feed-poll']) {
    it(`reports "${area}" failures`, () => {
      expect(SOURCE).toContain(`area: '${area}'`);
    });
  }

  it('keeps the console line as well, for local debugging', () => {
    // Telemetry replaces silence, not the developer's only tool.
    expect(SOURCE).toContain('Balance check failed on');
    expect(SOURCE).toContain('Live feed poll failed');
  });

  it('reports BEFORE the console call, so a throwing console cannot hide it', () => {
    const reported = SOURCE.indexOf("area: 'balance'");
    const logged = SOURCE.indexOf('Balance check failed on');
    expect(reported).toBeGreaterThan(0);
    expect(reported).toBeLessThan(logged);
  });
});
