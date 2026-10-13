/**
 * H13 — stake amounts must use the token's own decimals.
 *
 * `escrowFlow` used `TOKENS.USDT_DECIMALS` (a hard-coded 6) for every
 * `parseUnits` on the WRITE path, while the balance READ path
 * (`fetchLiveOnChainBalances`) reads `decimals()` from the token. The two
 * disagree the moment the payment token is not 6-decimal:
 *
 *   on an 18-decimal token, `createDuel(…, parseUnits("1", 6))` deposits 1e6
 *   base units = 1e-12 tokens while the UI advertises a 1-token stake.
 *
 * The joiner's check uses the same wrong constant, so nothing catches it — the
 * duel is simply funded at a scale nobody intended.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

vi.mock('./firebase', () => ({ getDb: () => null }));

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
import { approveUsdt, createDuel, getTokenDecimals, resetTokenDecimalsCache } from './escrowFlow';

const TOKEN = '0x' + '77'.repeat(20);

function fakeProvider(decimals: number) {
  const calls: { method: string; params?: unknown[] }[] = [];
  return {
    calls,
    async request({ method, params }: { method: string; params?: unknown[] }) {
      calls.push({ method, params });
      switch (method) {
        case 'eth_chainId':
          return '0x13882';
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
        case 'eth_call': {
          const data = String((params?.[0] as { data?: string })?.data ?? '');
          if (data.startsWith('0x313ce567')) {
            // decimals()
            return '0x' + decimals.toString(16).padStart(64, '0');
          }
          return '0x' + '0'.repeat(64);
        }
        default:
          return null;
      }
    },
  };
}

/** The uint256 argument of an approve/transfer call. */
function lastWord(data: string): bigint {
  const clean = data.replace(/^0x/, '');
  return BigInt('0x' + clean.slice(-64));
}

describe('token decimals (audit H13)', () => {
  beforeEach(() => {
    localStorage.clear();
    realWeb3Manager.disconnect();
    realWeb3Manager.bindActiveProvider(null);
    // The cache is module-level and immutable per token, so a test with a
    // different token must clear it explicitly.
    resetTokenDecimalsCache();
  });

  it('reads decimals from the token', async () => {
    const provider = fakeProvider(18);
    realWeb3Manager.bindActiveProvider(provider);

    expect(await getTokenDecimals()).toBe(18);
  });

  it('approves the stake in the token’s own units', async () => {
    const provider = fakeProvider(18);
    realWeb3Manager.bindActiveProvider(provider);

    void approveUsdt(1).catch(() => undefined);
    await vi.waitFor(() => {
      expect(provider.calls.some((c) => c.method === 'eth_sendTransaction')).toBe(true);
    });

    const sent = provider.calls.find((c) => c.method === 'eth_sendTransaction');
    const data = String((sent?.params?.[0] as { data?: string })?.data ?? '');
    expect(lastWord(data)).toBe(10n ** 18n);
  });

  it('locks the stake in the token’s own units', async () => {
    const provider = fakeProvider(18);
    realWeb3Manager.bindActiveProvider(provider);

    void createDuel('0x' + '00'.repeat(32), 2).catch(() => undefined);
    await vi.waitFor(() => {
      expect(provider.calls.some((c) => c.method === 'eth_sendTransaction')).toBe(true);
    });

    const sent = provider.calls.find((c) => c.method === 'eth_sendTransaction');
    const data = String((sent?.params?.[0] as { data?: string })?.data ?? '');
    expect(lastWord(data)).toBe(2n * 10n ** 18n);
  });

  it('a 6-decimal token still works', async () => {
    const provider = fakeProvider(6);
    realWeb3Manager.bindActiveProvider(provider);

    void approveUsdt(1).catch(() => undefined);
    await vi.waitFor(() => {
      expect(provider.calls.some((c) => c.method === 'eth_sendTransaction')).toBe(true);
    });

    const sent = provider.calls.find((c) => c.method === 'eth_sendTransaction');
    const data = String((sent?.params?.[0] as { data?: string })?.data ?? '');
    expect(lastWord(data)).toBe(10n ** 6n);
  });
});
