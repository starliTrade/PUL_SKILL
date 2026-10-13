/**
 * M31 — the client XP engine must agree with the server's, vector for vector.
 *
 * Progression moved to the server (audit M31), so the formula exists twice:
 * `api/xp.py` (authoritative — what the ledger stores) and `xpSystem.ts` (what
 * practice mode and the UI still compute). The shared fixture
 * `tests/fixtures/xp_vectors.json` is the contract; `tests/unit/test_xp_parity.py`
 * asserts the Python side against the same file.
 */
import { describe, it, expect } from 'vitest';
import * as fs from 'node:fs';
import * as path from 'node:path';

import { XPSystem } from './xpSystem';

interface Vector {
  outcome: 'win' | 'loss' | 'void';
  stake: number;
  yourTimeMs: number;
  currentXP: number;
  winStreak: number;
  expected: Record<string, number>;
}

const VECTORS: Vector[] = JSON.parse(
  fs.readFileSync(path.resolve(process.cwd(), 'tests/fixtures/xp_vectors.json'), 'utf8')
);

describe('XP engine parity with the server (audit M31)', () => {
  it('the vector file is not empty', () => {
    expect(VECTORS.length).toBeGreaterThanOrEqual(8);
  });

  it('matches every vector', () => {
    for (const v of VECTORS) {
      const got = XPSystem.calculateMatchXP(
        v.outcome,
        v.stake,
        v.yourTimeMs,
        v.currentXP,
        v.winStreak
      ) as unknown as Record<string, number>;
      for (const [key, expected] of Object.entries(v.expected)) {
        expect(got[key], `${key} for ${JSON.stringify(v)}`).toBe(expected);
      }
    }
  });

  it('the streak bonus can actually fire', () => {
    const first = XPSystem.calculateMatchXP('win', 1, 250, 0, 1);
    const second = XPSystem.calculateMatchXP('win', 1, 250, 0, 2);
    expect(first.streakBonusXP).toBe(0);
    expect(second.streakBonusXP).toBe(30);
  });
});
