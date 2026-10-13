/**
 * M26 — player search must work by playerId, not only by hex address.
 *
 * `searchPlayers` only queried `users/{address}` for inputs starting with
 * `0x`. A player who wanted to add a friend by the tag they actually see
 * ("SwiftBlade#42") got an empty list — the feature only worked for someone
 * who already knew the friend's 42-character address.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const firestore = vi.hoisted(() => ({
  getDocs: vi.fn(),
  where: vi.fn((field: string, op: string, value: unknown) => ({ __where: [field, op, value] })),
  collection: vi.fn((_db: unknown, name: string) => ({ __collection: name })),
  query: vi.fn((...args: unknown[]) => ({ __query: args })),
  limit: vi.fn((n: number) => ({ __limit: n })),
  doc: vi.fn((_db: unknown, col: string, id: string) => ({ __doc: [col, id] })),
  getDoc: vi.fn(),
  setDoc: vi.fn(),
  deleteDoc: vi.fn(),
  orderBy: vi.fn(),
  onSnapshot: vi.fn(),
}));

vi.mock('firebase/firestore', () => firestore);

vi.mock('./firebase', () => ({
  getDb: () => ({ __db: true }),
  syncToFirestore: async () => undefined,
}));

import { realWeb3Manager } from './realWeb3';

function snapshotOf(rows: Array<{ id: string; data: Record<string, unknown> }>) {
  return {
    forEach: (cb: (docSnap: { id: string; data: () => Record<string, unknown> }) => void) => {
      rows.forEach((r) => cb({ id: r.id, data: () => r.data }));
    },
  };
}

describe('player search (audit M26)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('finds a player by their playerId tag', async () => {
    firestore.getDocs.mockResolvedValue(
      snapshotOf([
        {
          id: '0x' + 'aa'.repeat(20),
          data: {
            address: '0x' + 'aa'.repeat(20),
            playerId: 'SwiftBlade#42',
            level: 3,
            xp: 120,
            wins: 5,
            totalMatches: 10,
            bestReactionMs: 210,
          },
        },
      ]),
    );

    const results = await realWeb3Manager.searchPlayers('SwiftBlade#42');

    expect(results).toHaveLength(1);
    expect(results[0].playerId).toBe('SwiftBlade#42');
    expect(results[0].address).toBe('0x' + 'aa'.repeat(20));
    // The query must have targeted the playerId field.
    expect(firestore.where).toHaveBeenCalledWith('playerId', '==', 'SwiftBlade#42');
  });

  it('still finds a player by their address', async () => {
    const addr = '0x' + 'bb'.repeat(20);
    firestore.getDoc.mockResolvedValue({
      exists: () => true,
      data: () => ({ address: addr, playerId: 'IronFalcon#7', level: 2, xp: 40, wins: 1, totalMatches: 2 }),
    });

    const results = await realWeb3Manager.searchPlayers(addr);

    expect(results).toHaveLength(1);
    expect(results[0].playerId).toBe('IronFalcon#7');
  });

  it('returns nothing for an empty query', async () => {
    expect(await realWeb3Manager.searchPlayers('   ')).toEqual([]);
    expect(firestore.getDocs).not.toHaveBeenCalled();
  });
});
