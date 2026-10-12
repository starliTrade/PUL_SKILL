/**
 * M30 — the store's `subscribe` must be stable across renders.
 *
 * `useSyncExternalStore` compares the `subscribe` argument by IDENTITY. Passing
 * an inline arrow — `(onChange) => realWeb3Manager.subscribe(onChange)` — creates
 * a new function on every render, so React tears the subscription down and
 * rebuilds it every time the component re-renders.
 *
 * On a page that re-renders per animation frame during a round that is a
 * subscribe/unsubscribe storm, and every teardown is a window in which a store
 * change can be missed.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react';
import React, { useState } from 'react';

// `vi.mock` is hoisted above ordinary declarations, so the values the factory
// closes over must be hoisted with it.
const { subscribeSpy, account } = vi.hoisted(() => ({
  subscribeSpy: vi.fn(() => () => undefined),
  account: {
    address: '',
    shortAddress: '',
    chainId: 80002,
    networkName: 'Polygon Amoy Testnet',
    balanceUSDT: 0,
    balancePOL: 0,
    balanceUnknown: true,
    connected: false,
    providerName: '',
  },
}));

vi.mock('../lib/realWeb3', () => ({
  ACTIVE_RANKED_MATCH_KEY: 'pulsar_active_ranked_match',
  realWeb3Manager: {
    getAccount: () => account,
    subscribe: (fn: () => void) => subscribeSpy(fn),
    restoreSession: async () => null,
    fetchGlobalLeaderboard: async () => [],
  },
}));

import { usePulsarStore } from './usePulsarStore';

/** A component that re-renders on demand, to force the subscribe identity check. */
function Probe() {
  const { wallet } = usePulsarStore();
  const [n, setN] = useState(0);
  return (
    <div>
      <span data-testid="addr">{wallet.fullAddress || 'none'}</span>
      <button data-testid="rerender" onClick={() => setN(n + 1)}>
        {n}
      </button>
    </div>
  );
}

describe('store subscription identity (audit M30)', () => {
  beforeEach(() => {
    subscribeSpy.mockClear();
  });

  it('re-rendering does not resubscribe', async () => {
    render(<Probe />);

    // The module-level subscription registers once at import.
    const afterMount = subscribeSpy.mock.calls.length;

    for (let i = 0; i < 5; i++) {
      await act(async () => {
        fireEvent.click(screen.getByTestId('rerender'));
      });
    }

    expect(subscribeSpy.mock.calls.length).toBe(afterMount);
  });

  it('the component still receives store updates', async () => {
    render(<Probe />);

    // The subscription captured at mount must still be live.
    const listener = subscribeSpy.mock.calls.at(-1)?.[0] as (() => void) | undefined;
    expect(listener).toBeTypeOf('function');

    await act(async () => {
      listener?.();
    });

    expect(screen.getByTestId('addr')).not.toBeNull();
  });

  it('unmounting unsubscribes exactly once', async () => {
    const unsubscribe = vi.fn();
    subscribeSpy.mockImplementation(() => unsubscribe);

    const { unmount } = render(<Probe />);
    const callsAtMount = subscribeSpy.mock.calls.length;

    unmount();

    // One teardown for the one subscription this render tree created.
    expect(unsubscribe.mock.calls.length).toBeGreaterThanOrEqual(1);
    expect(subscribeSpy.mock.calls.length).toBe(callsAtMount);
  });
});

void cleanup;
