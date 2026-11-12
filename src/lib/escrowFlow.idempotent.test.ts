/**
 * Audit M-07 — the deposit steps must be idempotent against CHAIN state.
 *
 * `approveUsdt` prompted the wallet unconditionally, so a retried flow (reload,
 * second tab, a re-tap after a network hiccup) asked the player to approve the
 * same stake again. And because `createDuel`/`joinDuel` key on the match id, the
 * loser of a two-tab race got "Match already exists" — which the UI showed as a
 * failure over money that had already been deposited.
 *
 * A server-side idempotency key cannot fix a chain write. The allowance and the
 * duel status ARE the idempotency state, and these tests pin that the code reads
 * them instead of guessing.
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

import { approveUsdt, isDuplicateDepositError, resetTokenDecimalsCache } from './escrowFlow';

const OWNER = '0x' + '11'.repeat(20);

function providerWithAllowance(allowanceUnits: bigint) {
  const sent: string[] = [];
  return {
    sent,
    async request({ method, params }: { method: string; params?: unknown[] }) {
      switch (method) {
        case 'eth_chainId':
          return '0x13882';
        case 'eth_accounts':
        case 'eth_requestAccounts':
          return [OWNER];
        case 'eth_blockNumber':
          return '0x1';
        case 'eth_gasPrice':
          return '0x' + (30_000_000_000).toString(16);
        case 'eth_estimateGas':
          return '0x' + (100_000).toString(16);
        case 'eth_sendTransaction':
          sent.push(JSON.stringify(params?.[0] ?? {}));
          return '0x' + 'ab'.repeat(32);
        case 'eth_call': {
          const data = String((params?.[0] as { data?: string })?.data ?? '');
          if (data.startsWith('0x313ce567')) {
            // decimals() → 6
            return '0x' + (6).toString(16).padStart(64, '0');
          }
          // allowance(...) → the amount the test wants
          return '0x' + allowanceUnits.toString(16).padStart(64, '0');
        }
        default:
          return null;
      }
    },
  };
}

describe('approve is idempotent against the allowance (audit M-07)', () => {
  beforeEach(() => {
    resetTokenDecimalsCache();
    localStorage.clear();
    const provider = providerWithAllowance(0n);
    (window as unknown as { ethereum: unknown }).ethereum = provider;
  });

  it('does NOT prompt the wallet when the allowance already covers the stake', async () => {
    const provider = providerWithAllowance(5_000_000n); // 5 USDT at 6 decimals
    (window as unknown as { ethereum: unknown }).ethereum = provider;

    const hash = await approveUsdt(1);
    expect(hash).toBe('');
    expect(provider.sent).toEqual([]);
  });

  it('DOES approve when the allowance is short', async () => {
    const provider = providerWithAllowance(500_000n); // 0.5 USDT
    (window as unknown as { ethereum: unknown }).ethereum = provider;

    // The fake provider never mines, so `tx.wait()` would hang; the assertion is
    // that the TRANSACTION IS SENT, which is the part that costs a wallet prompt.
    const pending = approveUsdt(1);
    pending.catch(() => undefined);
    await new Promise((r) => setTimeout(r, 100));

    expect(provider.sent).toHaveLength(1);
    // The approve selector for approve(address,uint256)
    expect(provider.sent[0]).toContain('095ea7b3');
  });

  it('treats a stake equal to the allowance as already approved', async () => {
    const provider = providerWithAllowance(1_000_000n); // exactly 1 USDT
    (window as unknown as { ethereum: unknown }).ethereum = provider;

    expect(await approveUsdt(1)).toBe('');
    expect(provider.sent).toEqual([]);
  });
});

describe('a duplicate deposit is not a failure (audit M-07)', () => {
  it('recognises the contract reverts that mean "already done"', () => {
    expect(isDuplicateDepositError(new Error('execution reverted: Match already exists'))).toBe(true);
    expect(isDuplicateDepositError(new Error('execution reverted: Match not available'))).toBe(true);
    expect(isDuplicateDepositError(new Error('reverted: Match is not active'))).toBe(true);
  });

  it('does not swallow a real failure', () => {
    expect(isDuplicateDepositError(new Error('insufficient funds for gas'))).toBe(false);
    expect(isDuplicateDepositError(new Error('user rejected the request'))).toBe(false);
    expect(isDuplicateDepositError(undefined)).toBe(false);
  });
});
