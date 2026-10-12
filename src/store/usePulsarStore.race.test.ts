/**
 * H14 — a slow profile load must not land under a different account.
 *
 * `reloadUserDataIfStale` sets `lastLoadedAddress` BEFORE the async
 * `loadUserDataAsync` resolves, and the `.then` writes `userData` regardless of
 * whether the account is still the same. So:
 *
 *   connect A  -> load A starts (slow)
 *   switch B   -> load B starts (fast) and lands
 *   A's response arrives last -> userData = A's wins/XP/history
 *
 * ...while `account.address` is B. The UI shows one person's stats under
 * another person's wallet. A disconnected wallet can be populated the same way.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

type Listener = () => void;

const listeners = new Set<Listener>();
let currentAccount = {
  address: '',
  shortAddress: '',
  chainId: 80002,
  networkName: 'Polygon Amoy Testnet',
  balanceUSDT: 0,
  balancePOL: 0,
  balanceUnknown: true,
  connected: false,
  providerName: 'MetaMask',
};

const pending = new Map<string, (data: unknown) => void>();

vi.mock('../lib/realWeb3', () => ({
  realWeb3Manager: {
    getAccount: () => currentAccount,
    subscribe: (fn: Listener) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    loadUserDataAsync: (address: string) =>
      new Promise((resolve) => {
        pending.set(address.toLowerCase(), resolve);
      }),
    restoreSession: async () => null,
    fetchGlobalLeaderboard: async () => [],
  },
}));

import { getStoreSnapshot } from './usePulsarStore';

const A = '0x' + 'aa'.repeat(20);
const B = '0x' + 'bb'.repeat(20);

function profileFor(address: string, wins: number, tag: string) {
  return {
    address,
    playerId: tag,
    vaultBalance: 0,
    wins,
    losses: 0,
    voids: 0,
    totalMatches: wins,
    bestReactionMs: 200,
    avgReactionMs: 250,
    xp: wins * 10,
    level: 1,
    savedFriends: [],
    history: [],
  };
}

function connect(address: string) {
  currentAccount = { ...currentAccount, address, connected: true };
  listeners.forEach((fn) => fn());
}

function disconnect() {
  currentAccount = { ...currentAccount, address: '', connected: false };
  listeners.forEach((fn) => fn());
}

describe('account switching (audit H14)', () => {
  beforeEach(() => {
    // Do NOT clear `listeners`: the store registers its subscription at module
    // import, and clearing would disconnect it for every later test.
    pending.clear();
    currentAccount = { ...currentAccount, address: '', connected: false };
  });

  it('a late response for a previous account is dropped', async () => {
    const { getStoreSnapshot: getSnapshot } = await import('./usePulsarStore');

    connect(A); // load A starts and hangs
    connect(B); // load B starts

    pending.get(B)!(profileFor(B, 7, 'Bravo'));
    await Promise.resolve();
    await Promise.resolve();

    // A finally answers — for an account we already left.
    pending.get(A)!(profileFor(A, 99, 'Alpha'));
    await Promise.resolve();
    await Promise.resolve();

    const state = getSnapshot();
    expect(state.account.address).toBe(B);
    expect(state.userData.playerId).toBe('Bravo');
    expect(state.userData.wins).toBe(7);
  });

  it('a response that arrives after disconnect is dropped', async () => {
    const { getStoreSnapshot: getSnapshot } = await import('./usePulsarStore');

    connect(A);
    disconnect();
    pending.get(A)!(profileFor(A, 99, 'Alpha'));
    await Promise.resolve();
    await Promise.resolve();

    const state = getSnapshot();
    expect(state.account.connected).toBe(false);
    expect(state.userData.playerId).not.toBe('Alpha');
  });

  it('the current account still loads normally', async () => {
    const { getStoreSnapshot: getSnapshot } = await import('./usePulsarStore');

    connect(A);
    pending.get(A)!(profileFor(A, 3, 'Alpha'));
    await Promise.resolve();
    await Promise.resolve();

    const state = getSnapshot();
    expect(state.userData.playerId).toBe('Alpha');
    expect(state.userData.wins).toBe(3);
  });
});
