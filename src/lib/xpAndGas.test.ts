/**
 * Phase 7 / M45 + M41 — the level curve and the gas floor.
 *
 * **M45.** `getLevel` and `getXPForLevel` are meant to be inverses, but one
 * floors and the other rounds:
 *
 *   getLevel(xp)   = floor((xp / 100) ** (1/1.5)) + 1
 *   getXPForLevel(l) = round(100 * (l - 1) ** 1.5)
 *
 * `getXPForLevel(3)` is 283, and `getLevel(283)` is 2 — so a player who reaches
 * exactly the XP for level 3 is shown as level 2. The boundary is off by the
 * rounding, and it is off at every level where `(l-1)**1.5` is not an integer.
 *
 * **M41.** `safeGasPrice()` floors the gas price at 30 gwei on EVERY chain. On
 * Polygon mainnet that is right. On an L2 whose gas is a fraction of a gwei it
 * makes every transaction cost tens of times more than needed — and the user
 * pays it.
 */
import { describe, it, expect } from 'vitest';

import { XPSystem } from './xpSystem';
import { gasFloorWei } from './escrowFlow';

describe('the level curve is an exact inverse (audit M45)', () => {
  it('getLevel(getXPForLevel(l)) === l for every level', () => {
    const wrong: string[] = [];
    for (let level = 2; level <= 60; level++) {
      const xp = XPSystem.getXPForLevel(level);
      const back = XPSystem.getLevel(xp);
      if (back !== level) wrong.push(`level ${level}: xp=${xp} -> ${back}`);
    }
    expect(wrong, `the curve is not invertible:\n${wrong.join('\n')}`).toEqual([]);
  });

  it('one XP below a level threshold is still the previous level', () => {
    for (let level = 3; level <= 60; level++) {
      const threshold = XPSystem.getXPForLevel(level);
      expect(XPSystem.getLevel(threshold - 1)).toBe(level - 1);
    }
  });

  it('level 1 is the floor', () => {
    expect(XPSystem.getLevel(0)).toBe(1);
    expect(XPSystem.getLevel(1)).toBe(1);
    expect(XPSystem.getXPForLevel(1)).toBe(0);
  });

  it('the curve is monotonically increasing', () => {
    let previous = 0;
    for (let level = 2; level <= 60; level++) {
      const xp = XPSystem.getXPForLevel(level);
      expect(xp).toBeGreaterThan(previous);
      previous = xp;
    }
  });
});

describe('the gas floor is per-chain (audit M41)', () => {
  it('Polygon mainnet keeps the 30 gwei floor', () => {
    // Polygon's node floor is ~25-30 gwei; without this, wallet suggestions
    // dip below it and eth_sendRawTransaction reverts with code 32603.
    expect(gasFloorWei(137)).toBe(30_000_000_000n);
  });

  it('a low-gas chain does not pay a 30 gwei floor', () => {
    // Amoy (the testnet) and L2s have far cheaper gas. A 30 gwei floor there is
    // tens of times more than needed, and the user pays it.
    const amoy = gasFloorWei(80002);
    expect(amoy).toBeLessThan(30_000_000_000n);
    expect(amoy).toBeGreaterThan(0n);
  });

  it('an unknown chain gets a conservative but not absurd floor', () => {
    const unknown = gasFloorWei(999999);
    expect(unknown).toBeGreaterThan(0n);
    expect(unknown).toBeLessThanOrEqual(30_000_000_000n);
  });
});
