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
import { XPSystem } from '../lib/xpSystem';

const MATCH = {
  id: 'm1',
  game: 'reaction',
  result: 'win' as const,
  entryFee: 1,
  prize: 1.96,
  opponentTime: 300,
  yourTime: 200,
  timestamp: Date.now(),
  // A server-settled duel: the ledger is authoritative for this one.
  ranked: true,
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

  it('does not reconcile a PRACTICE match against the ranked ledger', async () => {
    // Practice has no settlement behind it, so the ledger knows nothing about
    // it. Reconciling anyway replaced the practice XP — which is real and
    // locally earned — with the ranked-only numbers, resetting a connected
    // player's progression to 0 after every training round.
    h.fetchPlayerStats.mockResolvedValue({
      available: true,
      wins: 99,
      losses: 0,
      voids: 0,
      totalMatches: 99,
      xp: 99999,
      level: 40,
      winStreak: 9,
      bestReactionMs: 150,
      avgReactionMs: 200,
      lastXpAwarded: 0,
    });

    const { result } = renderHook(() => usePulsarStore());
    await act(async () => {
      await result.current.recordMatch({ ...MATCH, ranked: false });
    });

    expect(h.fetchPlayerStats).not.toHaveBeenCalled();
    expect(h.stored?.wins).toBe(1);
    expect(h.stored?.xp).not.toBe(99999);
  });

  it('describes the SERVER total, so level and progress bar agree', async () => {
    // 4200 XP is level 13 on the shared curve (the parity test pins the two
    // curves together). The point here is that the progress bar describes the
    // server's total, not the local estimate that was computed a moment ago.
    h.fetchPlayerStats.mockResolvedValue({
      available: true,
      wins: 12,
      losses: 3,
      voids: 1,
      totalMatches: 16,
      xp: 4200,
      level: 13,
      winStreak: 4,
      bestReactionMs: 180,
      avgReactionMs: 240,
      lastXpAwarded: 205,
    });

    const { result } = renderHook(() => usePulsarStore());
    let summary: Record<string, number | string> | undefined;
    await act(async () => {
      summary = (await result.current.recordMatch(MATCH)) as unknown as Record<string, number | string>;
    });

    expect(summary?.newTotalXP).toBe(4200);
    expect(summary?.newLevel).toBe(13);
    expect(summary?.currentLevelXP).toBe(4200 - XPSystem.getXPForLevel(13));
    expect(summary?.totalAwardedXP).toBe(205);
  });
});
