/**
 * H15b — the identity lock must be VISIBLE.
 *
 * H15 made `accountsChanged` and `chainChanged` refuse while a ranked match is
 * live, and recorded the reason on `identityLockedReason`. Nothing renders it:
 * the player's wallet switch is refused and the app says nothing, which is the
 * same "your action was silently ignored" experience the fix was meant to
 * remove.
 *
 * This is the same class of gap as H17b — a mechanism with no path to the user.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, act, cleanup } from '@testing-library/react';
import React from 'react';

type Listener = () => void;

const { manager, account, listeners } = vi.hoisted(() => {
  const listeners = new Set<() => void>();
  const account = {
    address: '0x' + '11'.repeat(20),
    shortAddress: '0x1111...1111',
    chainId: 80002,
    networkName: 'Polygon Amoy Testnet',
    balanceUSDT: 25,
    balancePOL: 1,
    balanceUnknown: false,
    connected: true,
    providerName: 'MetaMask',
  };
  return {
    account,
    listeners,
    manager: {
      getAccount: () => account,
      subscribe: (fn: Listener) => {
        listeners.add(fn);
        return () => listeners.delete(fn);
      },
      loadUserDataAsync: async () => ({
        address: '0x' + '11'.repeat(20),
        playerId: 'Tester',
        vaultBalance: 0,
        wins: 0,
        losses: 0,
        voids: 0,
        totalMatches: 0,
        bestReactionMs: 0,
        avgReactionMs: 0,
        xp: 0,
        level: 1,
        savedFriends: [],
        history: [],
      }),
      restoreSession: async () => null,
      fetchGlobalLeaderboard: async () => [],
      identityLockedReason: '',
    },
  };
});

vi.mock('../lib/realWeb3', () => ({
  ACTIVE_RANKED_MATCH_KEY: 'pulsar_active_ranked_match',
  realWeb3Manager: manager,
}));

vi.mock('../i18n/LanguageContext', () => ({
  useLanguage: () => ({ t: (key: string) => key, currentLanguage: 'en', setLanguage: vi.fn() }),
}));

import { getStoreSnapshot } from './usePulsarStore';
import { IdentityLockBanner } from '../components/IdentityLockBanner';

function notify() {
  listeners.forEach((fn) => fn());
}

describe('identity lock visibility (audit H15b)', () => {
  beforeEach(async () => {
    manager.identityLockedReason = '';
    // The store's snapshot is a CACHE rebuilt on notify, so clearing the reason
    // on the manager is not enough — without this the previous test's snapshot
    // leaks into the next one.
    await act(async () => {
      notify();
    });
  });

  afterEach(() => {
    cleanup();
  });

  it('the store carries the reason', async () => {
    manager.identityLockedReason = 'A ranked match is in progress.';
    await act(async () => {
      notify();
    });

    expect(getStoreSnapshot().identityLockedReason).toBe('A ranked match is in progress.');
  });

  it('the banner renders the reason', async () => {
    manager.identityLockedReason = 'A ranked match is in progress.';
    await act(async () => {
      notify();
    });

    render(<IdentityLockBanner />);
    expect(screen.getByText(/ranked match is in progress/i)).not.toBeNull();
  });

  it('the banner renders nothing when there is no lock', () => {
    render(<IdentityLockBanner />);
    expect(screen.queryByTestId('pulsar-identity-lock')).toBeNull();
  });

  it('the banner clears when the lock clears', async () => {
    manager.identityLockedReason = 'A ranked match is in progress.';
    await act(async () => {
      notify();
    });
    render(<IdentityLockBanner />);
    expect(screen.getByTestId('pulsar-identity-lock')).not.toBeNull();

    manager.identityLockedReason = '';
    await act(async () => {
      notify();
    });

    expect(screen.queryByTestId('pulsar-identity-lock')).toBeNull();
  });
});
