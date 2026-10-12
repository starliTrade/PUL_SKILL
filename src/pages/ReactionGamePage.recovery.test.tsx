/**
 * H11 — refresh recovery must actually settle the match.
 *
 * `restoreBo3FromServer` is `useCallback(..., [])` and calls
 * `finishServerMatch`, whose first line is `if (!serverSession || !serverMatch)
 * return;`. With empty deps the callback captures the FIRST render's
 * `finishServerMatch`, whose closure has both values null — so the call returns
 * immediately and does nothing.
 *
 * Consequence: after a page reload of a DECIDED ranked match, the winner's
 * client never submits `settleDuel`. The prize sits in escrow until the refund
 * horizon, and the player has no idea why.
 *
 * The test drives the real page: seed a decided match, render, and assert the
 * settlement is actually requested.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react';
import React from 'react';

const settleMatch = vi.fn(async () => ({
  status: 'settled',
  matchId: 'a'.repeat(32),
  winner: '0x' + '11'.repeat(20),
  winnerTimeMs: 200,
  loserTimeMs: 300,
  serverNonce: 1,
  deadline: Math.floor(Date.now() / 1000) + 600,
  oracleAddress: '0x' + 'ef'.repeat(20),
  signature: '0x' + 'ab'.repeat(65),
  validatedTimes: {},
}));
const getMatch = vi.fn();
const ensureSession = vi.fn(async () => ({ token: 't', address: '0x' + '11'.repeat(20) }));

vi.mock('../lib/gameServerClient', () => ({
  gameServerConfigured: () => true,
  ensureSession: (...a: unknown[]) => ensureSession(...(a as [])),
  // Audit H1: the submit path measures the round trip.
  measureServerRttMs: async () => 20,
  queueForMatch: vi.fn(async () => ({ status: 'active' })),
  commitRound: vi.fn(async () => undefined),
  revealRoundTarget: vi.fn(async () => ({ targetMs: 100, resultProof: 'proof' })),
  submitRoundResult: vi.fn(async () => ({ accepted: true, reason: '' })),
  settleMatch: (...a: unknown[]) => settleMatch(...(a as [])),
  claimMatch: vi.fn(async () => ({ ok: true, onChainProof: true })),
  getMatch: (...a: unknown[]) => getMatch(...(a as [])),
  matchIdToBytes32: async () => '0x' + '00'.repeat(32),
}));

vi.mock('../store/usePulsarStore', () => ({
  usePulsarStore: () => ({
    wallet: {
      address: '0x' + '11'.repeat(20),
      fullAddress: '0x' + '11'.repeat(20),
      connected: true,
      balanceUSDT: 100,
      balanceUnknown: false,
    },
    recordMatch: vi.fn(),
  }),
}));

vi.mock('../lib/realWeb3', () => ({
  // Audit H15: the page imports this key to persist the live match.
  ACTIVE_RANKED_MATCH_KEY: 'pulsar_active_ranked_match',
  realWeb3Manager: {
    getActiveEip1193Provider: () => ({ request: vi.fn() }),
    disconnect: vi.fn(),
    bindActiveProvider: vi.fn(),
  },
}));

vi.mock('../lib/sound', () => ({
  sounds: {
    playTick: vi.fn(),
    playGo: vi.fn(),
    playHit: vi.fn(),
    playWin: vi.fn(),
    playLoss: vi.fn(),
    playError: vi.fn(),
  },
}));

vi.mock('canvas-confetti', () => ({ default: vi.fn() }));

vi.mock('../lib/escrowFlow', () => ({
  settleDuel: vi.fn(async () => '0x' + 'cd'.repeat(32)),
  refundTimeoutMatch: vi.fn(),
  escrowStatus: () => ({ configured: true, escrowAddress: '0x' + 'ab'.repeat(20), message: '' }),
  approveUsdt: vi.fn(),
  createDuel: vi.fn(),
  joinDuel: vi.fn(),
  getDuelState: vi.fn(),
  getPendingWithdrawal: vi.fn(async () => '0'),
  withdrawPending: vi.fn(),
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

const MATCH_ID = 'a'.repeat(32);
const ME = '0x' + '11'.repeat(20);

/** A match the player has already WON 2-0 — the terminal recovery branch. */
function decidedView() {
  return {
    matchId: MATCH_ID,
    stake: 1,
    status: 'active',
    winner: '',
    createdAt: 0,
    rounds: 3,
    me: ME,
    opponentJoined: true,
    opponent: '0x' + '22'.repeat(20),
    youAreCreator: true,
    youAreJoiner: false,
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

describe('refresh recovery (audit H11)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    getMatch.mockResolvedValue(decidedView());
  });

  afterEach(() => {
    cleanup();
  });

  it('a reload of a decided match actually requests settlement', async () => {
    render(<ReactionGamePage onNavigate={vi.fn()} stakeAmount={1} />);

    // Let the mount effects settle — `persistActiveMatch(null)` runs on mount
    // and REMOVES the persisted match, so the seed must come after.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    localStorage.setItem('pulsar_active_ranked_match', JSON.stringify({ matchId: MATCH_ID, stake: 1 }));

    await act(async () => {
      fireEvent.click(screen.getByTestId('pulsar-verify-node'));
      await Promise.resolve();
      await Promise.resolve();
    });

    await vi.waitFor(() => {
      expect(settleMatch).toHaveBeenCalled();
    }, { timeout: 3000 });
  });
});
