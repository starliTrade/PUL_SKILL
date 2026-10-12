/**
 * H15 — a live ranked match must lock the player's identity.
 *
 * `accountsChanged` called `setConnectedAddress(...)` immediately and
 * `chainChanged` called `window.location.reload()` unconditionally. During a
 * staked duel that is destructive in two different ways:
 *
 *   - switching accounts changes `wallet.fullAddress` while the server session,
 *     the match and the escrow deposits all belong to the PREVIOUS address, so
 *     the player is suddenly playing as someone else (and `iWon` is evaluated
 *     against the wrong wallet);
 *   - the reload destroys the in-memory provider — on WalletConnect that means
 *     the session is gone mid-match.
 *
 * The lock is keyed on the persisted live match, which is what the game page
 * already writes.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

vi.mock('./firebase', () => ({ getDb: () => null }));

const ME = '0x' + '11'.repeat(20);
const OTHER = '0x' + 'bb'.repeat(20);

type Handler = (...args: unknown[]) => void;

function fakeProvider() {
  const handlers = new Map<string, Handler>();
  return {
    handlers,
    emit(event: string, ...args: unknown[]) {
      handlers.get(event)?.(...args);
    },
    async request({ method }: { method: string }) {
      switch (method) {
        case 'eth_chainId':
          return '0x13882';
        case 'eth_accounts':
        case 'eth_requestAccounts':
          return [ME];
        default:
          return null;
      }
    },
    on(event: string, fn: Handler) {
      handlers.set(event, fn);
    },
  };
}

/** Import a fresh manager with `window.ethereum` already in place. */
async function freshManager(provider: ReturnType<typeof fakeProvider>) {
  vi.resetModules();
  (window as unknown as { ethereum: unknown }).ethereum = provider;
  const mod = await import('./realWeb3');
  return mod.realWeb3Manager;
}

const reloadSpy = vi.fn();

describe('identity lock during a live match (audit H15)', () => {
  beforeEach(() => {
    localStorage.clear();
    delete (window as unknown as { ethereum?: unknown }).ethereum;
    reloadSpy.mockClear();
    // jsdom makes `window.location.reload` non-configurable, so `vi.spyOn`
    // throws; replacing the whole `location` object is the way in.
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...window.location, reload: reloadSpy },
    });
  });

  it('an account switch mid-match does not change the identity', async () => {
    const provider = fakeProvider();
    localStorage.setItem('pulsar_active_ranked_match', JSON.stringify({ matchId: 'a'.repeat(32) }));
    const manager = await freshManager(provider);

    await manager.connect('MetaMask');
    expect(manager.getAccount().address).toBe(ME);

    provider.emit('accountsChanged', [OTHER]);

    // `setConnectedAddress` is async, so asserting immediately would pass even
    // against the unfixed code — the switch simply had not landed yet. Give it
    // every chance to.
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(manager.getAccount().address).toBe(ME);
    expect(manager.getAccount().address).not.toBe(OTHER);
  });

  it('the refusal is explained to the player', async () => {
    const provider = fakeProvider();
    localStorage.setItem('pulsar_active_ranked_match', JSON.stringify({ matchId: 'a'.repeat(32) }));
    const manager = await freshManager(provider);
    await manager.connect('MetaMask');

    provider.emit('accountsChanged', [OTHER]);
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(manager.identityLockedReason).toMatch(/match/i);
  });

  it('a chain switch mid-match does not reload the page', async () => {
    const provider = fakeProvider();
    localStorage.setItem('pulsar_active_ranked_match', JSON.stringify({ matchId: 'a'.repeat(32) }));
    const manager = await freshManager(provider);
    await manager.connect('MetaMask');

    provider.emit('chainChanged', '0x89');

    expect(reloadSpy).not.toHaveBeenCalled();
    expect(manager.identityLockedReason).toMatch(/network/i);
  });

  it('without a live match an account switch still works', async () => {
    const provider = fakeProvider();
    const manager = await freshManager(provider);
    await manager.connect('MetaMask');

    provider.emit('accountsChanged', [OTHER]);

    await vi.waitFor(() => {
      expect(manager.getAccount().address).toBe(OTHER);
    });
  });

  it('without a live match a chain switch still reloads', async () => {
    const provider = fakeProvider();
    const manager = await freshManager(provider);
    await manager.connect('MetaMask');

    provider.emit('chainChanged', '0x89');

    expect(reloadSpy).toHaveBeenCalled();
  });
});
