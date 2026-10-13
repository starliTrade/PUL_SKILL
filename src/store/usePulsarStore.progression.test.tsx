/**
 * M31 — progression belongs to the server.
 *
 * Wins/XP/level/streak were computed and stored entirely by the client, so a
 * player could edit localStorage and award themselves a level, and the
 * documented streak bonus could never fire (`winStreak` was never passed to
 * the XP calculation). The ledger now owns the numbers; the client's local
 * estimate is only a fallback for when the server cannot answer.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';

const h = vi.hoisted(() => ({
  account: {
    address: '0x' + 'aa'.repeat(20),
    shortAddress: '0xaaaa...aaaa',
    chainId: 80002,
    networkName: 'Polygon Amoy Testnet',
    balanceUSDT: 10,
    balancePOL: 1,
    balanceUnknown: false,
    connected: true,
    providerName: 'MetaMask',
  },
  stored: null as Record<string, unknown> | null,
  fetchPlayerStats: vi.fn(),
}));

vi.mock('../lib/realWeb3', () => ({
  RealWeb3Manager: {
    getPlayerTagForAddress: () => 'Tag#1',
  },
  realWeb3Manager: {
    getAccount: () => h.account,
    subscribe: () => () => {},
    restoreSession: async () => null,
    loadUserDataAsync: async (address: string) => ({
      address,
      playerId: 'Tag#1',
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
    saveUserDataAsync: async (data: Record<string, unknown>) => {
      h.stored = data;
    },
    fetchGlobalLeaderboard: async () => [],
    getPlayerTagForAddress: () => 'Tag#1',
  },
}));

vi.mock('../lib/gameServerClient', () => ({
  ensureSession: vi.fn(),
  clearServerSession: vi.fn(),
  claimUsername: vi.fn(),
  GameServerUnavailableError: class extends Error {},
  fetchPlayerStats: (...a: unknown[]) => h.fetchPlayerStats(...(a as [])),
}));

import { usePulsarStore } from './usePulsarStore';

const MATCH = {
  id: 'm1',
  game: 'reaction',
  result: 'win' as const,
  entryFee: 1,
  prize: 1.96,
  opponentTime: 300,
  yourTime: 200,
  timestamp: Date.now(),
};

describe('server-authoritative progression (audit M31)', () => {
  beforeEach(() => {
    h.stored = null;
    h.fetchPlayerStats.mockReset();
  });

  it('takes the ledger numbers over the local estimate', async () => {
    h.fetchPlayerStats.mockResolvedValue({
      available: true,
      wins: 12,
      losses: 3,
      voids: 1,
      totalMatches: 16,
      xp: 4200,
      level: 9,
      winStreak: 4,
      bestReactionMs: 180,
      avgReactionMs: 240,
      lastXpAwarded: 205,
    });

    const { result } = renderHook(() => usePulsarStore());
    await act(async () => {
      await result.current.recordMatch(MATCH);
    });

    expect(h.fetchPlayerStats).toHaveBeenCalled();
    expect(h.stored?.wins).toBe(12);
    expect(h.stored?.xp).toBe(4200);
    expect(h.stored?.level).toBe(9);
    expect(h.stored?.winStreak).toBe(4);
  });

  it('falls back to the local estimate when the ledger cannot answer', async () => {
    h.fetchPlayerStats.mockResolvedValue({ available: false });

    const { result } = renderHook(() => usePulsarStore());
    let summary: { totalAwardedXP: number } | undefined;
    await act(async () => {
      summary = (await result.current.recordMatch(MATCH)) as { totalAwardedXP: number };
    });

    // The local estimate still awards XP so the player sees something.
    expect(summary?.totalAwardedXP ?? 0).toBeGreaterThan(0);
    expect(h.stored?.wins).toBe(1);
  });

  it('does not lose the match history when the ledger answers', async () => {
    h.fetchPlayerStats.mockResolvedValue({
      available: true,
      wins: 1,
      losses: 0,
      voids: 0,
      totalMatches: 1,
      xp: 205,
      level: 2,
      winStreak: 1,
      bestReactionMs: 200,
      avgReactionMs: 200,
      lastXpAwarded: 205,
    });

    const { result } = renderHook(() => usePulsarStore());
    await act(async () => {
      await result.current.recordMatch(MATCH);
    });

    expect(Array.isArray(h.stored?.history)).toBe(true);
    expect((h.stored?.history as unknown[]).length).toBe(1);
  });
});
