/**
 * H17b — the client must be able to claim a deferred payout.
 *
 * Audit H17 gave the contract `pendingWithdrawals` + `withdraw()` so that a
 * payout the token refuses (Tether blacklist, a paused token, a contract that
 * reverts on receipt) is credited instead of reverting the whole settlement.
 * The contract is correct — and NOTHING in the client calls it.
 *
 * So a player whose payout was deferred has money waiting on-chain and no way
 * to reach it from the UI. The fix is not in the contract; it is the missing
 * path to it.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

vi.mock('./firebase', () => ({ getDb: () => null }));

// `chain.ts` reads `import.meta.env` at module load, so stubbing the env inside
// a test is too late — the module must be mocked with a configured escrow.
vi.mock('./chain', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./chain')>();
  return {
    ...actual,
    ESCROW: { address: '0x' + 'ab'.repeat(20), source: 'env', verified: false },
    TOKENS: { ...actual.TOKENS, USDT: '0x' + '77'.repeat(20) },
    isPaymentTokenConfigured: () => true,
    isEscrowConfigured: () => true,
  };
});

import { realWeb3Manager } from './realWeb3';
import { withdrawPending, getPendingWithdrawal } from './escrowFlow';

type Call = { method: string; params?: unknown[] };

function fakeProvider(opts: { pending?: bigint } = {}) {
  const calls: Call[] = [];
  return {
    calls,
    async request({ method, params }: Call) {
      calls.push({ method, params });
      switch (method) {
        case 'eth_chainId':
          return '0x13882'; // Polygon Amoy — the client default
        case 'eth_accounts':
        case 'eth_requestAccounts':
          return ['0x' + '11'.repeat(20)];
        case 'eth_blockNumber':
          return '0x1';
        case 'eth_gasPrice':
          return '0x' + (30_000_000_000).toString(16);
        case 'eth_estimateGas':
          return '0x' + (100_000).toString(16);
        case 'eth_sendTransaction':
          return '0x' + 'ab'.repeat(32);
        case 'eth_getTransactionReceipt':
          return { status: '0x1', transactionHash: '0x' + 'ab'.repeat(32) };
        case 'eth_call':
          // pendingWithdrawals(address) -> uint256
          return '0x' + (opts.pending ?? 0n).toString(16).padStart(64, '0');
        default:
          return null;
      }
    },
  };
}

describe('deferred payouts (audit H17b)', () => {
  beforeEach(() => {
    localStorage.clear();
    realWeb3Manager.disconnect();
    realWeb3Manager.bindActiveProvider(null);
    // The escrow configuration comes from the mocked ./chain module above.
  });

  it('exposes a way to read the pending balance', async () => {
    const provider = fakeProvider({ pending: 9_800_000n });
    realWeb3Manager.bindActiveProvider(provider);

    const pending = await getPendingWithdrawal('0x' + '11'.repeat(20));
    expect(pending).toBe('9.8');
  });

  it('exposes a way to claim it', async () => {
    const provider = fakeProvider({ pending: 9_800_000n });
    realWeb3Manager.bindActiveProvider(provider);

    // `withdrawPending` awaits `tx.wait()`, which polls a fake provider forever.
    // What matters here is that the transaction is SENT; the mining wait is
    // ethers' business, and the contract's own tests cover the payout.
    void withdrawPending().catch(() => undefined);
    await vi.waitFor(() => {
      expect(provider.calls.filter((c) => c.method === 'eth_sendTransaction')).toHaveLength(1);
    });
  });

  it('the claim targets the escrow, not the token', async () => {
    const provider = fakeProvider({ pending: 9_800_000n });
    realWeb3Manager.bindActiveProvider(provider);

    void withdrawPending().catch(() => undefined);
    await vi.waitFor(() => {
      expect(provider.calls.filter((c) => c.method === 'eth_sendTransaction')).toHaveLength(1);
    });

    const sent = provider.calls.find((c) => c.method === 'eth_sendTransaction');
    const tx = (sent?.params?.[0] ?? {}) as { to?: string };
    expect(tx.to?.toLowerCase()).toBe(('0x' + 'ab'.repeat(20)).toLowerCase());
  });

  it('refuses to claim when there is nothing pending', async () => {
    const provider = fakeProvider({ pending: 0n });
    realWeb3Manager.bindActiveProvider(provider);

    // A no-op claim would look like a successful one; the contract reverts, and
    // the client should say so before spending gas.
    await expect(withdrawPending()).rejects.toThrow(/nothing to withdraw/i);
  });
});
