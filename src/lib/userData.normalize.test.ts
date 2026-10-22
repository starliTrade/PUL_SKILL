/**
 * Audit H-17 (2026-10-22) — a ledger document is not a user profile.
 *
 * `users/{address}` is written by the settlement ledger. It has wins, XP and
 * reaction times, but no `history` and no `savedFriends`. It used to be cast
 * straight to `UserWalletData`, so on the first ranked duel `recordMatch` ran
 * `[match, ...undefined]` and threw, silently: the result screen never showed XP.
 */
import { describe, expect, it } from 'vitest';
import { normalizeUserData } from './realWeb3';

const ADDR = '0x' + '11'.repeat(20);
const TAG = 'Player#1111';

describe('normalizeUserData', () => {
  it('gives a ledger document the arrays the UI iterates', () => {
    const out = normalizeUserData({ wins: 3, xp: 480, level: 4 }, ADDR, TAG);

    expect(out.history).toEqual([]);
    expect(out.savedFriends).toEqual([]);
    expect(out.wins).toBe(3);
    expect(out.xp).toBe(480);
    expect(out.level).toBe(4);
  });

  it('keeps real arrays intact', () => {
    const history = [{ id: 'm1' } as never];
    const out = normalizeUserData({ history, savedFriends: [ADDR] }, ADDR, TAG);
    expect(out.history).toBe(history);
    expect(out.savedFriends).toEqual([ADDR]);
  });

  it('never leaves a numeric field undefined or NaN', () => {
    const out = normalizeUserData({ wins: 'nonsense' as never }, ADDR, TAG);
    expect(out.wins).toBe(0);
    expect(Number.isNaN(out.level)).toBe(false);
    expect(out.level).toBe(1);
  });

  it('always returns the address in lower case, with a display tag', () => {
    const out = normalizeUserData({}, ADDR.toUpperCase(), TAG);
    expect(out.address).toBe(ADDR);
    expect(out.playerId).toBe(TAG);
  });

  it('survives a completely empty document', () => {
    expect(() => normalizeUserData(null, ADDR, TAG)).not.toThrow();
  });
});
