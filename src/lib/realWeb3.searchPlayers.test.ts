/**
 * M26 + M-19 — player search: by tag, through the server.
 *
 * M26: `searchPlayers` only queried `users/{address}` for inputs starting with
 * `0x`, so a player who wanted to add a friend by the tag they actually see
 * ("SwiftBlade#42") got an empty list.
 *
 * M-19 (2026-10-22): the search used to read `users/*` from the BROWSER. That
 * collection is the settlement ledger — wallet, wins, XP, reaction averages,
 * history — and was world-readable only so a friend card could render. The
 * search now goes through GET /api/players/search, which returns five display
 * fields. These tests pin that the client no longer touches Firestore for it and
 * never invents a player who does not exist.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const server = vi.hoisted(() => ({
  searchPlayers: vi.fn(),
}));

vi.mock('./gameServerClient', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./gameServerClient')>();
  return { ...actual, searchPlayers: server.searchPlayers };
});

vi.mock('./firebase', () => ({
  getDb: () => ({ __db: true }),
  syncToFirestore: async () => undefined,
}));

import { realWeb3Manager } from './realWeb3';

const ADDRESS = '0x' + 'aa'.repeat(20);
const SESSION = { address: ADDRESS, token: 't', issuedAt: Date.now() };

describe('player search', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    localStorage.setItem('pulsar.server.session.v1', JSON.stringify(SESSION));
  });

  it('finds a player by their playerId tag', async () => {
    server.searchPlayers.mockResolvedValue({
      players: [
        {
          address: ADDRESS,
          playerId: 'SwiftBlade#42',
          level: 3,
          wins: 5,
          totalMatches: 10,
        },
      ],
    });

    const found = await realWeb3Manager.searchPlayers('SwiftBlade#42');

    expect(server.searchPlayers).toHaveBeenCalledWith(expect.anything(), 'SwiftBlade#42');
    expect(found.map((p) => p.playerId)).toEqual(['SwiftBlade#42']);
  });

  it('finds a player by their address', async () => {
    server.searchPlayers.mockResolvedValue({
      players: [
        { address: ADDRESS, playerId: '', level: 1, wins: 0, totalMatches: 0 },
      ],
    });

    const found = await realWeb3Manager.searchPlayers(ADDRESS);

    expect(found[0].address).toBe(ADDRESS);
    // No tag: the display falls back to a generated name, as everywhere else.
    expect(found[0].playerId).toMatch(/^Player#/);
  });

  it('never fabricates a player for an unknown address', async () => {
    // The old code invented a "new challenger" profile for any 42-char hex
    // string. That is how a UI ends up showing a person who does not exist.
    server.searchPlayers.mockResolvedValue({ players: [] });

    const found = await realWeb3Manager.searchPlayers('0x' + 'bb'.repeat(20));

    expect(found).toEqual([]);
  });

  it('returns nothing without a server session instead of reading Firestore', async () => {
    localStorage.clear();
    const found = await realWeb3Manager.searchPlayers('SwiftBlade#42');
    expect(found).toEqual([]);
    expect(server.searchPlayers).not.toHaveBeenCalled();
  });

  it('swallows a server failure into an empty list (the form must not crash)', async () => {
    server.searchPlayers.mockRejectedValue(new Error('503'));
    await expect(realWeb3Manager.searchPlayers('x')).resolves.toEqual([]);
  });
});
