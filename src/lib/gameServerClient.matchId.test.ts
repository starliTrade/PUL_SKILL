/**
 * M38 — `matchIdToBytes32` must not require a secure context.
 *
 * It called `crypto.subtle.digest("SHA-256", ...)`. `crypto.subtle` exists ONLY
 * in a secure context — HTTPS or localhost. On a plain-HTTP deployment (a LAN
 * address, an HTTP tunnel, a staging box) it is `undefined`, so the call throws
 * and the ENTIRE on-chain deposit flow fails: the player cannot create or join
 * a duel at all, and the error surfaces as an opaque "cannot read property of
 * undefined".
 *
 * The hash is a pure function of the match id, so it has no business depending
 * on the page's transport security.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import { matchIdToBytes32 } from './gameServerClient';

/** The well-known SHA-256 of "abc". */
const ABC_SHA256 = '0xba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad';

describe('match id hashing (audit M38)', () => {
  const original = Object.getOwnPropertyDescriptor(globalThis.crypto, 'subtle');

  beforeEach(() => {
    vi.resetModules();
  });

  afterEach(() => {
    if (original) {
      Object.defineProperty(globalThis.crypto, 'subtle', original);
    }
  });

  it('hashes correctly with crypto.subtle available', async () => {
    expect(await matchIdToBytes32('abc')).toBe(ABC_SHA256);
  });

  it('hashes correctly WITHOUT crypto.subtle (plain HTTP)', async () => {
    // An insecure context: `crypto` exists but `subtle` does not.
    Object.defineProperty(globalThis.crypto, 'subtle', {
      configurable: true,
      get: () => undefined,
    });

    expect(await matchIdToBytes32('abc')).toBe(ABC_SHA256);
  });

  it('produces the same hash in both contexts', async () => {
    const secure = await matchIdToBytes32('a-real-match-id');

    Object.defineProperty(globalThis.crypto, 'subtle', {
      configurable: true,
      get: () => undefined,
    });
    const insecure = await matchIdToBytes32('a-real-match-id');

    expect(insecure).toBe(secure);
  });

  it('the hash is 32 bytes', async () => {
    Object.defineProperty(globalThis.crypto, 'subtle', {
      configurable: true,
      get: () => undefined,
    });

    const hash = await matchIdToBytes32('anything');
    expect(hash).toMatch(/^0x[0-9a-f]{64}$/);
  });
});
