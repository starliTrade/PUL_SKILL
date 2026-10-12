/**
 * C3 regression — money transactions must be signed by the wallet the user
 * actually connected with.
 *
 * Audit C3: `getActiveEip1193Provider()` returned `wcProvider` (if alive) and
 * otherwise `window.ethereum`, and nothing ever recorded which EIP-6963
 * provider the user picked. A user who connected Coinbase/Rabby through
 * EIP-6963 while MetaMask sat on `window.ethereum` had every `approveUsdt` /
 * `createDuel` / `settleDuel` sent through MetaMask — a different account, or a
 * rejected SIWE session, or funds moved from a wallet the user never chose.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

vi.mock('./firebase', () => ({
  getDb: () => null,
  // The profile path is not what this test is about; it must not hit the network.
  syncToFirestore: async () => undefined,
}));

import { realWeb3Manager } from './realWeb3';

type FakeProvider = {
  name: string;
  request: (args: { method: string; params?: unknown[] }) => Promise<unknown>;
  calls: string[];
};

function makeProvider(name: string, chainIdHex = '0x89'): FakeProvider {
  const calls: string[] = [];
  return {
    name,
    calls,
    async request({ method }: { method: string }) {
      calls.push(method);
      switch (method) {
        case 'eth_requestAccounts':
        case 'eth_accounts':
          return [`0x${name.toLowerCase().padEnd(40, '0').slice(0, 40)}`];
        case 'eth_chainId':
          return chainIdHex;
        default:
          return null;
      }
    },
  };
}

function detail(provider: FakeProvider, name: string) {
  return {
    info: { name, uuid: `uuid-${name}`, rdns: `com.${name.toLowerCase()}`, icon: '' },
    provider,
  } as never;
}

describe('active EIP-1193 provider (audit C3)', () => {
  beforeEach(() => {
    localStorage.clear();
    delete (window as unknown as { ethereum?: unknown }).ethereum;
    // Balances are a network concern; the provider identity is not.
    vi.spyOn(realWeb3Manager, 'fetchLiveOnChainBalances').mockResolvedValue({
      usdt: 0,
      pol: 0,
      ok: false,
    });
  });

  it('returns the EIP-6963 provider the user connected with, not window.ethereum', async () => {
    const metaMask = makeProvider('MetaMask');
    const coinbase = makeProvider('Coinbase');
    (window as unknown as { ethereum: FakeProvider }).ethereum = metaMask;

    await realWeb3Manager.connectEIP6963(detail(coinbase, 'Coinbase'));

    expect(realWeb3Manager.getActiveEip1193Provider()).toBe(coinbase);
  });

  it('does not fall back to window.ethereum when a different wallet is connected', async () => {
    const metaMask = makeProvider('MetaMask');
    const rabby = makeProvider('Rabby');
    (window as unknown as { ethereum: FakeProvider }).ethereum = metaMask;

    await realWeb3Manager.connectEIP6963(detail(rabby, 'Rabby'));

    const active = realWeb3Manager.getActiveEip1193Provider();
    expect(active).not.toBe(metaMask);
    expect(active).toBe(rabby);
  });

  it('returns window.ethereum when that is what the user connected with', async () => {
    const metaMask = makeProvider('MetaMask');
    (window as unknown as { ethereum: FakeProvider }).ethereum = metaMask;

    realWeb3Manager.bindActiveProvider(metaMask);

    expect(realWeb3Manager.getActiveEip1193Provider()).toBe(metaMask);
  });

  it('a WalletConnect zombie does not shadow the connected injected provider', async () => {
    const injected = makeProvider('MetaMask');
    (window as unknown as { ethereum: FakeProvider }).ethereum = injected;
    realWeb3Manager.bindActiveProvider(injected);

    // A provider object that reports `connected` but has no session/accounts is
    // the iOS-suspend zombie the existing guard exists for.
    (realWeb3Manager as unknown as { wcProvider: unknown }).wcProvider = {
      connected: true,
      session: undefined,
      accounts: [],
    };

    expect(realWeb3Manager.getActiveEip1193Provider()).toBe(injected);
  });
});
