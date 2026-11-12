/**
 * Balance display and the sufficiency gate (audit 2026-10-24).
 *
 * `realWeb3.fetchLiveOnChainBalances` used to round the on-chain balance to two
 * decimals with `Math.round(usdt * 100) / 100`, and `LobbyPage` gates entry with
 *
 *     if (gameMode === 'real' && !stats.balanceUnknown && stats.balance < selectedStake)
 *
 * Rounding UP means a wallet holding 4.996 USDT displays 5.00 and passes the
 * `stake = 5` gate. The player then signs a transaction the contract must reject
 * — "execution reverted" in their wallet, after they have already committed to
 * the duel. That is the same class of defect as `probe.ok = true` (H-17): the
 * screen asserted something about the player's money that was not true.
 *
 * Money is never rounded UP for a sufficiency claim. The display truncates, in
 * the same direction as the integer arithmetic the contract uses.
 *
 * These tests pin the direction, not an implementation: `floorToDecimals` can be
 * rewritten, but 4.999999 must never present as 5.00 to a gate that compares it
 * against a 5 USDT stake.
 */

import { describe, expect, it } from 'vitest';

import { floorToDecimals } from './money';

describe('a balance is never rounded up', () => {
  it('4.996 USDT does not become 5.00', () => {
    // The exact case that passed the stake-5 gate with too little money.
    expect(floorToDecimals(4.996, 2)).toBe(4.99);
    expect(floorToDecimals(4.996, 2)).toBeLessThan(5);
  });

  it('an exact balance survives', () => {
    expect(floorToDecimals(5, 2)).toBe(5);
    expect(floorToDecimals(5.0, 2)).toBe(5);
    expect(floorToDecimals(1234.56, 2)).toBe(1234.56);
  });

  it('dust below one cent is reported as zero, not as a cent', () => {
    expect(floorToDecimals(0.004, 2)).toBe(0);
    expect(floorToDecimals(0.009, 2)).toBe(0);
  });

  it('the old rounding is a counterexample, and it is documented as one', () => {
    const roundedUp = Math.round(4.996 * 100) / 100; // 5
    expect(roundedUp).toBe(5);
    expect(roundedUp >= 5).toBe(true); // would pass the gate
    expect(floorToDecimals(4.996, 2) >= 5).toBe(false); // does not
  });

  it('never exceeds the true value, for a spread of amounts', () => {
    for (const value of [0, 0.001, 0.01, 0.019, 1.005, 4.999, 5.555, 999.999]) {
      const shown = floorToDecimals(value, 2);
      expect(shown, `${value}`).toBeLessThanOrEqual(value + 1e-9);
    }
  });

  it('handles NaN and Infinity without producing NaN for the gate', () => {
    // `NaN < 5` is false, so a NaN balance would PASS the sufficiency gate.
    // Returning 0 makes the comparison fail closed instead.
    expect(floorToDecimals(Number.NaN, 2)).toBe(0);
    expect(floorToDecimals(Number.POSITIVE_INFINITY, 2)).toBe(0);
  });
});
