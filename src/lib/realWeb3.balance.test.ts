/**
 * H12 — a profile save must not overwrite the on-chain balance.
 *
 * `saveUserDataAsync` wrote `this.currentAccount.balanceUSDT = data.vaultBalance`
 * and notified. `vaultBalance` is a deprecated field that is 0.0 on every fresh
 * profile and is never updated (P1.16 removed the vault), so after any
 * `recordMatch` or `updatePlayerTag` a wallet that had just shown a real balance
 * (e.g. $25.00, `balanceUnknown === false`) flipped to **$0.00 as a stated
 * fact** — and tripped the insufficient-balance gate in the lobby and the game.
 *
 * The chain is the only source of truth for the balance; `balanceUnknown` says
 * whether it has been read yet.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

vi.mock('./firebase', () => ({ getDb: () => null }));

import { realWeb3Manager } from './realWeb3';

const ME = '0x' + '11'.repeat(20);

function fakeProvider() {
  return {
    async request({ method }: { method: string }) {
      switch (method) {
        case 'eth_chainId':
          return '0x13882';
        case 'eth_requestAccounts':
        case 'eth_accounts':
          return [ME];
        default:
          return null;
      }
    },
  };
}

function profile(vaultBalance: number) {
  return {
    address: ME,
    playerId: 'Tester',
    vaultBalance,
    wins: 3,
    losses: 1,
    voids: 0,
    totalMatches: 4,
    bestReactionMs: 210,
    avgReactionMs: 240,
    xp: 120,
    level: 2,
    savedFriends: [],
    history: [],
  };
}

describe('profile saves and the on-chain balance (audit H12)', () => {
  beforeEach(() => {
    localStorage.clear();
    realWeb3Manager.disconnect();
    realWeb3Manager.bindActiveProvider(null);
    (window as unknown as { ethereum: unknown }).ethereum = fakeProvider();
    vi.spyOn(realWeb3Manager, 'fetchLiveOnChainBalances').mockResolvedValue({
      usdt: 25,
      pol: 1,
      ok: true,
    });
  });

  it('a profile save does not zero a balance that came from the chain', async () => {
    await realWeb3Manager.connect('MetaMask');
    await vi.waitFor(() => {
      expect(realWeb3Manager.getAccount().balanceUSDT).toBe(25);
    });

    await realWeb3Manager.saveUserDataAsync(profile(0));

    expect(realWeb3Manager.getAccount().balanceUSDT).toBe(25);
    expect(realWeb3Manager.getAccount().balanceUnknown).toBe(false);
  });

  it('a profile save does not invent a balance either', async () => {
    await realWeb3Manager.connect('MetaMask');
    await vi.waitFor(() => {
      expect(realWeb3Manager.getAccount().balanceUSDT).toBe(25);
    });

    // A stale profile claiming 999 must not become the displayed balance.
    await realWeb3Manager.saveUserDataAsync(profile(999));

    expect(realWeb3Manager.getAccount().balanceUSDT).toBe(25);
  });

  it('the profile is still persisted', async () => {
    await realWeb3Manager.connect('MetaMask');
    await realWeb3Manager.saveUserDataAsync(profile(0));

    const stored = JSON.parse(localStorage.getItem(`pulsar_data_${ME}`) || '{}');
    expect(stored.wins).toBe(3);
    expect(stored.playerId).toBe('Tester');
  });
});
