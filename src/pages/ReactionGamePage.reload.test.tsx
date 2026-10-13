/**
 * Audit HIGH-4 + HIGH-5 — refresh recovery must survive a REAL reload.
 *
 * HIGH-4: the mount effect ran `persistActiveMatch(serverMatch)` with
 * `serverMatch === null` on the first render, which DELETES the persisted key
 * before `recoverServerMatch()` can read it. The feature was dead in
 * production; the old test seeded localStorage AFTER mount, an ordering that
 * never happens on a reload.
 *
 * HIGH-5: `restoreBo3FromServer` is `useCallback(..., [])`, so it holds the
 * FIRST render's `finishServerMatch` — whose captured `wallet.fullAddress` is
 * `''` because `restoreSession()` has not resolved yet. `iWon` is then false for
 * everyone, and a reloaded WINNER is recorded and shown as a loser.
 *
 * This test models the real sequence: the key exists BEFORE the first render,
 * the wallet arrives on a later render, and only then does the player tap.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react';
import React from 'react';

const MATCH_ID = 'a'.repeat(32);
const ME = '0x' + '11'.repeat(20);
const OPPONENT = '0x' + '22'.repeat(20);

const h = vi.hoisted(() => ({
  // The wallet the store reports on the NEXT render. Empty until the test says
  // otherwise, which is what a reload looks like before restoreSession resolves.
  wallet: { address: '', fullAddress: '', connected: false, balanceUSDT: 100, balanceUnknown: false },
  getMatch: vi.fn(),
  settleMatch: vi.fn(),
  createDuel: vi.fn(),
  queueForMatch: vi.fn(),
  recordMatch: vi.fn(async (_match?: { result?: string }) => ({ totalXP: 0, levelUp: false })),
}));

vi.mock('../lib/gameServerClient', () => ({
  gameServerConfigured: () => true,
  ensureSession: vi.fn(async () => ({ token: 't', address: ME })),
  measureServerRttMs: async () => 20,
  queueForMatch: (...a: unknown[]) => h.queueForMatch(...(a as [])),
  commitRound: vi.fn(async () => undefined),
  revealRoundTarget: vi.fn(async () => ({ targetMs: 100, resultProof: 'proof' })),
  submitRoundResult: vi.fn(async () => ({ accepted: true, reason: '' })),
  settleMatch: (...a: unknown[]) => h.settleMatch(...(a as [])),
  claimMatch: vi.fn(async () => ({ ok: true, onChainProof: true })),
  getMatch: (...a: unknown[]) => h.getMatch(...(a as [])),
  matchIdToBytes32: async () => '0x' + '00'.repeat(32),
}));

vi.mock('../store/usePulsarStore', () => ({
  usePulsarStore: () => ({
    wallet: h.wallet,
    stats: {
      balance: 100, balanceUnknown: false, wins: 0, losses: 0, voids: 0,
      totalMatches: 0, xp: 0, level: 1, winStreak: 0,
    },
    recordMatch: (...a: unknown[]) => h.recordMatch(...(a as [])),
  }),
}));

vi.mock('../lib/realWeb3', () => ({
  ACTIVE_RANKED_MATCH_KEY: 'pulsar_active_ranked_match',
  realWeb3Manager: {
    getActiveEip1193Provider: () => ({ request: vi.fn() }),
    disconnect: vi.fn(),
    bindActiveProvider: vi.fn(),
  },
}));

vi.mock('../lib/sound', () => ({
  sounds: {
    playTick: vi.fn(), playGo: vi.fn(), playHit: vi.fn(), playWin: vi.fn(),
    playLoss: vi.fn(), playError: vi.fn(), playClick: vi.fn(),
  },
}));

vi.mock('canvas-confetti', () => ({ default: vi.fn() }));

vi.mock('../lib/escrowFlow', () => ({
  settleDuel: vi.fn(async () => '0x' + 'cd'.repeat(32)),
  refundTimeoutMatch: vi.fn(),
  escrowStatus: () => ({ configured: true, escrowAddress: '0x' + 'ab'.repeat(20), message: '' }),
  approveUsdt: vi.fn(async () => '0x' + 'aa'.repeat(32)),
  createDuel: (...a: unknown[]) => h.createDuel(...(a as [])),
  joinDuel: vi.fn(async () => '0x' + 'cc'.repeat(32)),
  getDuelState: vi.fn(async () => ({ status: 2, player1: ME, player2: OPPONENT, stakeAmount: 0n, totalPool: 0n, winner: '' })),
  findSettlementTx: vi.fn(async () => ''),
  getPendingWithdrawal: vi.fn(async () => '0'),
  withdrawPending: vi.fn(),
  getTokenDecimals: vi.fn(async () => 6),
}));

vi.mock('../lib/monitoring', () => ({ reportError: vi.fn() }));

vi.mock('../lib/chain', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/chain')>();
  return {
    ...actual,
    isEscrowConfigured: () => true,
    ESCROW: { address: '0x' + 'ab'.repeat(20), source: 'env', verified: false },
    TREASURY: { address: '0x' + 'cd'.repeat(20), source: 'env', verified: false },
    ORACLE_SIGNER: { address: '0x' + 'ef'.repeat(20), source: 'env', verified: false },
  };
});

vi.mock('../components/ConnectWallet', () => ({ ConnectWallet: () => null }));
vi.mock('../components/DuelCertificateModal', () => ({ DuelCertificateModal: () => null }));
vi.mock('../components/PulsarCosmicBackground', () => ({ PulsarCosmicBackground: () => null }));

vi.mock('../i18n/LanguageContext', () => ({
  useLanguage: () => ({ t: (key: string) => key, currentLanguage: 'en', setLanguage: vi.fn() }),
}));

import { ReactionGamePage } from './ReactionGamePage';

/** A decided match the player WON 2-0. */
function decidedView() {
  return {
    matchId: MATCH_ID, stake: 1, status: 'active', winner: '', createdAt: 0, rounds: 3,
    me: ME, opponentJoined: true, opponent: OPPONENT, youAreCreator: true, youAreJoiner: false,
    myRounds: [
      { index: 0, committed: true, targetRevealed: true, submitted: true, valid: true, rejectReason: '' },
      { index: 1, committed: true, targetRevealed: true, submitted: true, valid: true, rejectReason: '' },
      { index: 2, committed: false, targetRevealed: false, submitted: false, valid: false, rejectReason: '' },
    ],
    myTimes: { '0': 200, '1': 210 },
    opponentTimes: { '0': 300, '1': 310 },
    opponentSubmitted: 2,
  };
}

describe('refresh recovery on a real reload (audit HIGH-4 + HIGH-5)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    h.wallet = { address: '', fullAddress: '', connected: false, balanceUSDT: 100, balanceUnknown: false };
    h.getMatch.mockResolvedValue(decidedView());
    h.settleMatch.mockResolvedValue({
      status: 'settled', matchId: MATCH_ID, winner: ME, winnerTimeMs: 200, loserTimeMs: 300,
      serverNonce: 1, deadline: Math.floor(Date.now() / 1000) + 600,
      oracleAddress: '0x' + 'ef'.repeat(20), signature: '0x' + 'ab'.repeat(65), validatedTimes: {},
    });
  });

  afterEach(() => {
    cleanup();
  });

  it('keeps the persisted match across the first render', async () => {
    // The key exists BEFORE the first render — what a reload actually looks like.
    localStorage.setItem('pulsar_active_ranked_match', JSON.stringify({ matchId: MATCH_ID, stake: 1 }));

    const { rerender } = render(<ReactionGamePage onNavigate={vi.fn()} stakeAmount={1} />);
    await act(async () => {
      await Promise.resolve();
    });

    expect(localStorage.getItem('pulsar_active_ranked_match')).not.toBeNull();
    rerender(<ReactionGamePage onNavigate={vi.fn()} stakeAmount={1} />);
  });

  it('resumes the duel instead of re-depositing, and records the WIN', async () => {
    localStorage.setItem('pulsar_active_ranked_match', JSON.stringify({ matchId: MATCH_ID, stake: 1 }));

    const { rerender } = render(<ReactionGamePage onNavigate={vi.fn()} stakeAmount={1} />);
    await act(async () => {
      await Promise.resolve();
    });

    // The wallet arrives (restoreSession resolved) and the page re-renders.
    h.wallet = { address: ME, fullAddress: ME, connected: true, balanceUSDT: 100, balanceUnknown: false };
    await act(async () => {
      rerender(<ReactionGamePage onNavigate={vi.fn()} stakeAmount={1} />);
      await Promise.resolve();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId('pulsar-verify-node'));
      await Promise.resolve();
      await Promise.resolve();
    });

    await vi.waitFor(() => {
      expect(h.getMatch).toHaveBeenCalled();
    }, { timeout: 3000 });

    // HIGH-4: recovery engaged, so the duel is resumed rather than re-queued
    // and re-deposited.
    expect(h.queueForMatch).not.toHaveBeenCalled();
    expect(h.createDuel).not.toHaveBeenCalled();

    // HIGH-5: the player WON this match; the reload must not turn it into a loss.
    await vi.waitFor(() => {
      expect(h.recordMatch).toHaveBeenCalled();
    }, { timeout: 3000 });
    const recorded = h.recordMatch.mock.calls[0][0] as { result?: string } | undefined;
    expect(recorded?.result).toBe('win');
  });
});
