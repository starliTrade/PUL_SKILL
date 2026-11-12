/**
 * Audit H-04 (2026-10-22) — the lobby feed must be built from real settlements.
 *
 * The old feed subscribed to Firestore and read `entryFee`, a field the server
 * never writes, so it was permanently empty; when a document lacked `result` it
 * defaulted to 'win'. These tests pin the honest shape: one row per side, no
 * invented fields, and an empty log means an empty feed.
 */
import { describe, expect, it } from 'vitest';
import { settlementsToFeedRows } from './realWeb3';
import type { SettlementRecord } from './gameServerClient';

const WINNER = '0x' + 'aa'.repeat(20);
const LOSER = '0x' + 'bb'.repeat(20);

const settlement = (over: Partial<SettlementRecord> = {}): SettlementRecord => ({
  matchId: 'a'.repeat(32),
  stake: 5,
  players: [WINNER, LOSER],
  winner: WINNER,
  settledAt: 1_700_000_000,
  winnerTimeMs: 210,
  loserTimeMs: 340,
  prize: 9.8,
  oracleAddress: '0x' + 'cc'.repeat(20),
  signature: '0xdeadbeef',
  ...over,
});

describe('settlementsToFeedRows', () => {
  it('produces one row per side with the real times and prizes', () => {
    const rows = settlementsToFeedRows([settlement()]);
    expect(rows).toHaveLength(2);

    const win = rows.find((r) => r.result === 'win')!;
    const loss = rows.find((r) => r.result === 'loss')!;

    expect(win.entryFee).toBe(5);
    expect(win.prize).toBe(9.8);
    expect(win.yourTime).toBe(210);
    expect(win.opponentTime).toBe(340);

    expect(loss.prize).toBe(0);
    expect(loss.yourTime).toBe(340);
    expect(loss.opponentTime).toBe(210);
  });

  it('never invents a winner for a settlement without one', () => {
    expect(settlementsToFeedRows([settlement({ winner: '' })])).toEqual([]);
  });

  it('reports a missing time as 0 rather than a plausible number', () => {
    const rows = settlementsToFeedRows([settlement({ winnerTimeMs: null, loserTimeMs: null })]);
    expect(rows.every((r) => r.yourTime === 0 && r.opponentTime === 0)).toBe(true);
  });

  it('an empty settlement log is an empty feed, not a fabricated one', () => {
    expect(settlementsToFeedRows([])).toEqual([]);
  });
});
