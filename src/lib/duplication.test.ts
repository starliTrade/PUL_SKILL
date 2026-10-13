/**
 * Plan item 8.20 — the duplicated rules stay unified.
 *
 * A source-level guard, because the failure mode is a NEW copy: someone writes
 * the prize formula or the best-of-three rule inline again, and the two copies
 * drift. Nothing else would notice until a payout disagreed with the UI.
 */
import { describe, it, expect } from 'vitest';
import * as fs from 'node:fs';
import * as path from 'node:path';

const ROOT = process.cwd();

function sourceFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    for (const entry of fs.readdirSync(path.join(ROOT, dir), { withFileTypes: true })) {
      const rel = `${dir}/${entry.name}`;
      if (entry.isDirectory()) walk(rel);
      else if (/\.(ts|tsx)$/.test(entry.name) && !/\.test\.(ts|tsx)$/.test(entry.name)) out.push(rel);
    }
  };
  walk('src');
  return out;
}

describe('duplicated rules are unified (plan item 8.20)', () => {
  it('the prize formula lives only in prizeForStake', () => {
    const offenders = sourceFiles().filter((rel) => {
      if (rel === 'src/lib/chain.ts') return false; // the definition
      const src = fs.readFileSync(path.join(ROOT, rel), 'utf8');
      // The formula, however it is spelled: `stake * 2 * winnerShareBps`.
      return /\*\s*2\s*\*\s*ECONOMY\.winnerShareBps|\*\s*2\s*\*\s*winnerShareBps/.test(src);
    });
    expect(offenders, `inline prize math in: ${offenders.join(', ')}`).toEqual([]);
  });

  it('the best-of-three rule lives only in bo3.ts', () => {
    const offenders = sourceFiles().filter((rel) => {
      if (rel === 'src/lib/bo3.ts') return false; // the definition
      const src = fs.readFileSync(path.join(ROOT, rel), 'utf8');
      // A literal `>= 2 ||` comparison between two scores is the rule.
      return /(userScore|opponentScore|playerScore)\s*>=\s*2\s*\|\|/.test(src);
    });
    expect(offenders, `inline best-of-three in: ${offenders.join(', ')}`).toEqual([]);
  });

  it('the WalletConnect account fallback lives only in wcAccounts', () => {
    const src = fs.readFileSync(path.join(ROOT, 'src/lib/realWeb3.ts'), 'utf8');
    // `activeSessionAccounts` is the primitive; everything else goes through
    // `wcAccounts`. One call site in the helper itself is expected.
    const calls = src.match(/this\.activeSessionAccounts\(/g) ?? [];
    expect(calls.length, `activeSessionAccounts called ${calls.length} times`).toBeLessThanOrEqual(1);

    // A bare `provider.accounts` read is the shape that drifted: it skips the
    // session fallback, so a session that survived a tab suspend looks like
    // "no accounts". Only the helper may read it.
    const bare = src
      .split('\n')
      .map((line, i) => ({ line, n: i + 1 }))
      .filter(({ line }) => /provider\??\.accounts/.test(line))
      .filter(({ line }) => !/^\s*(\/\/|\*|\/\*)/.test(line)) // comments explain the rule
      .filter(({ line }) => !/const direct = provider\?\.accounts/.test(line)); // the helper itself
    expect(bare.map((b) => `${b.n}: ${b.line.trim()}`), 'bare provider.accounts reads').toEqual([]);
  });
});
