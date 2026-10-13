/**
 * M36 regression — cancelling a WalletConnect pairing must actually tear the
 * relay down, and the stale-proposal purge must not skip keys.
 *
 * Audit M36 (two halves, one file):
 *
 *  1. `cancelPendingConnect()` dropped our only reference to a LIVE provider.
 *     `provider.connect()` opens the relay transport immediately, so
 *     `provider.connected` is already true while the wallet has not approved
 *     yet. The old guard (`if (!this.wcProvider.connected) disconnect()`) ran
 *     the teardown only in the case where there was nothing to tear down, and
 *     skipped exactly the live case: the relay socket stayed open and the
 *     `wc@2:` keys were never cleaned up.
 *
 *  2. The stale-proposal purge in `ensureWcProvider()` used a FORWARD loop.
 *     `localStorage` indices shift under the cursor as keys are removed, so
 *     every removal skipped the entry that slid into its slot — a purge of
 *     N proposal keys left roughly half of them behind. `main.tsx` already
 *     avoided this with a reverse loop; the provider path did not.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

vi.mock('./firebase', () => ({
  getDb: () => null,
  syncToFirestore: async () => undefined,
}));

// The provider class is loaded through a dynamic import; stub it so the purge
// path can run without a relay or a real Reown project.
const initCalls: unknown[] = [];
let initImpl: () => Promise<any> = async () => makeWcProvider();

vi.mock('@walletconnect/ethereum-provider', () => ({
  EthereumProvider: {
    init: (...args: unknown[]) => {
      initCalls.push(args);
      return initImpl();
    },
  },
}));

import { realWeb3Manager } from './realWeb3';

function makeWcProvider(overrides: Record<string, unknown> = {}) {
  return {
    connected: false,
    accounts: [] as string[],
    session: undefined as unknown,
    chainId: 137,
    on: () => {},
    disconnect: () => Promise.resolve(),
    ...overrides,
  };
}

const PROPOSAL_A = 'wc@2:core:0.3//proposal:aaa';
const PROPOSAL_B = 'wc@2:core:0.3//proposal:bbb';
const PROPOSAL_C = 'wc@2:core:0.3//proposal:ccc';
const SESSION_KEY = 'wc@2:core:0.3//session:keep';

describe('WalletConnect pairing teardown (audit M36)', () => {
  beforeEach(() => {
    localStorage.clear();
    initCalls.length = 0;
    initImpl = async () => makeWcProvider();

    // realWeb3Manager is a singleton; a provider left by one test would leak
    // into the next and make an assertion pass for the wrong reason.
    realWeb3Manager.disconnect();
    realWeb3Manager.bindActiveProvider(null);
    (realWeb3Manager as unknown as { wcProvider: unknown }).wcProvider = null;
    (realWeb3Manager as unknown as { wcInitPromise: unknown }).wcInitPromise = null;
    (realWeb3Manager as unknown as { wcEventsBound: boolean }).wcEventsBound = false;
    (realWeb3Manager as unknown as { wcConnectPromise: unknown }).wcConnectPromise = null;

    vi.spyOn(realWeb3Manager, 'fetchLiveOnChainBalances').mockResolvedValue({
      usdt: 0,
      pol: 0,
      ok: false,
    });
  });

  it('disconnects a LIVE provider when a pairing is cancelled', () => {
    const disconnect = vi.fn(() => Promise.resolve());
    // The relay is up (connected === true) but the wallet has not approved:
    // this is the state the user is in when they tap the cancel / X button.
    const live = makeWcProvider({ connected: true, disconnect });
    (realWeb3Manager as unknown as { wcProvider: unknown }).wcProvider = live;

    realWeb3Manager.cancelPendingConnect();

    expect(disconnect).toHaveBeenCalledTimes(1);
    expect((realWeb3Manager as unknown as { wcProvider: unknown }).wcProvider).toBeNull();
  });

  it('still tears down a provider that reports itself as not connected', () => {
    const disconnect = vi.fn(() => Promise.resolve());
    const dangling = makeWcProvider({ connected: false, disconnect });
    (realWeb3Manager as unknown as { wcProvider: unknown }).wcProvider = dangling;

    realWeb3Manager.cancelPendingConnect();

    expect(disconnect).toHaveBeenCalledTimes(1);
    expect((realWeb3Manager as unknown as { wcProvider: unknown }).wcProvider).toBeNull();
  });

  it('does not throw when there is nothing to cancel', () => {
    expect(() => realWeb3Manager.cancelPendingConnect()).not.toThrow();
  });

  it('purges EVERY stale proposal key before initialising the provider', async () => {
    localStorage.setItem('pulsar_reown_project_id', 'project-id-1234567890');
    localStorage.setItem(PROPOSAL_A, '1');
    localStorage.setItem(PROPOSAL_B, '2');
    localStorage.setItem(PROPOSAL_C, '3');
    localStorage.setItem(SESSION_KEY, '4');
    localStorage.setItem('pulsar_active_address', '0xabc');

    await (realWeb3Manager as unknown as { ensureWcProvider: () => Promise<unknown> }).ensureWcProvider();

    expect(localStorage.getItem(PROPOSAL_A)).toBeNull();
    expect(localStorage.getItem(PROPOSAL_B)).toBeNull();
    expect(localStorage.getItem(PROPOSAL_C)).toBeNull();
    // A live session must survive the purge — it is not a proposal.
    expect(localStorage.getItem(SESSION_KEY)).toBe('4');
    expect(localStorage.getItem('pulsar_active_address')).toBe('0xabc');
  });
});
