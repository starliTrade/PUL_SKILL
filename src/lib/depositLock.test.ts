/**
 * Audit M-07 — one deposit prompt per duel, across tabs.
 *
 * Two tabs (or a reload) both reaching the deposit phase opened two wallet
 * prompts for the same stake, and the loser of the race got a contract revert
 * ("Match already exists") that the UI showed as a failure over money that HAD
 * landed. A React ref cannot fix this: refs are per-tab and die on reload.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

import {
  acquireDepositLease,
  peekDepositLease,
  releaseDepositLease,
  renewDepositLease,
} from './depositLock';

const MATCH = 'a'.repeat(32);

describe('the deposit lease (audit M-07)', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useRealTimers();
  });

  it('grants the first caller and refuses the second', () => {
    const first = acquireDepositLease(MATCH);
    expect(first).not.toBeNull();

    const second = acquireDepositLease(MATCH);
    expect(second).toBeNull();
    expect(peekDepositLease(MATCH)?.token).toBe(first?.token);
  });

  it('is per match: a different duel is a different lock', () => {
    expect(acquireDepositLease(MATCH)).not.toBeNull();
    expect(acquireDepositLease('b'.repeat(32))).not.toBeNull();
  });

  it('expires on its own, so a closed tab cannot lock a player out', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-22T10:00:00Z'));
    const first = acquireDepositLease(MATCH, 60_000);
    expect(first).not.toBeNull();
    expect(acquireDepositLease(MATCH, 60_000)).toBeNull();

    vi.setSystemTime(new Date('2026-10-22T10:01:01Z'));
    const second = acquireDepositLease(MATCH, 60_000);
    expect(second).not.toBeNull();
    expect(second?.token).not.toBe(first?.token);
  });

  it('cannot be released by a caller that does not hold it', () => {
    const holder = acquireDepositLease(MATCH);
    const thief = { matchId: MATCH, token: 'not-the-token', expiresAt: Date.now() + 60_000 };
    releaseDepositLease(thief);
    expect(peekDepositLease(MATCH)?.token).toBe(holder?.token);
  });

  it('releases cleanly so the next flow can proceed', () => {
    const lease = acquireDepositLease(MATCH)!;
    releaseDepositLease(lease);
    expect(peekDepositLease(MATCH)).toBeNull();
    expect(acquireDepositLease(MATCH)).not.toBeNull();
  });

  it('renew fails after the lease was taken over', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-10-22T10:00:00Z'));
    const mine = acquireDepositLease(MATCH, 1000)!;
    vi.setSystemTime(new Date('2026-10-22T10:00:05Z'));
    const theirs = acquireDepositLease(MATCH, 60_000)!;
    expect(renewDepositLease(mine)).toBe(false);
    expect(theirs.token).not.toBe(mine.token);
  });

  it('degrades to "no lock" when storage is unavailable, instead of blocking', () => {
    // A private-mode browser has localStorage that throws on access. Refusing to
    // deposit there would be a worse bug than a double prompt.
    const original = Object.getOwnPropertyDescriptor(window, 'localStorage');
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      get() {
        throw new Error('SecurityError: storage disabled');
      },
    });
    try {
      expect(acquireDepositLease(MATCH)).not.toBeNull();
    } finally {
      if (original) Object.defineProperty(window, 'localStorage', original);
    }
  });
});
