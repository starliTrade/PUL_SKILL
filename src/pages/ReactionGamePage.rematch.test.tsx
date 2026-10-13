/**
 * M5 — a rematch must clear the previous match's settlement state.
 *
 * `handleRematch` resets `matchResult`, `lastRoundResult`, `bo3State`, `phase`
 * and the calibration target — but not `settlementTxHash`, `lastProof`,
 * `onchainAction`, `serverMatch` or `serverSession`. So after starting a new
 * duel the previous match's "view on explorer" link, its "prize claimed
 * on-chain" line and its retry/refund buttons can all render against the NEW
 * match — pointing at a transaction that has nothing to do with it.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react';
import React from 'react';

const TX_HASH = '0x' + 'cd'.repeat(32);

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
    // `recordMatch` is awaited with `.then` in the settle path.
    stats: {
      balance: 100,
      balanceUnknown: false,
      wins: 0,
      losses: 0,
      voids: 0,
      totalMatches: 0,
      xp: 0,
      level: 1,
      winStreak: 0,
    },
    recordMatch: vi.fn(async () => ({ totalXP: 0, levelUp: false })),
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
    playTick: vi.fn(),
    playGo: vi.fn(),
    playHit: vi.fn(),
    playWin: vi.fn(),
    playLoss: vi.fn(),
    playError: vi.fn(),
    playClick: vi.fn(),
  },
}));

vi.mock('canvas-confetti', () => ({ default: vi.fn() }));

vi.mock('../lib/escrowFlow', () => ({
  settleDuel: vi.fn(async () => TX_HASH),
  refundTimeoutMatch: vi.fn(),
  escrowStatus: () => ({ configured: true, escrowAddress: '0x' + 'ab'.repeat(20), message: '' }),
  approveUsdt: vi.fn(),
  createDuel: vi.fn(),
  joinDuel: vi.fn(),
  getDuelState: vi.fn(),
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

const MATCH_ID = 'a'.repeat(32);
const ME = '0x' + '11'.repeat(20);

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

/** Drive the page to the result screen with a settlement tx hash on it. */
async function reachResultWithTx() {
  getMatch.mockResolvedValue(decidedView());
  render(<ReactionGamePage onNavigate={vi.fn()} stakeAmount={1} />);

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
    expect(screen.queryByText(/↗/)).not.toBeNull();
  }, { timeout: 3000 }).catch(() => {
    throw new Error(`never reached the result screen. body=${(document.body.textContent || '').slice(0, 400)}`);
  });
}

describe('rematch resets the settlement state (audit M5)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  afterEach(() => {
    cleanup();
  });

  it('the previous settlement hash is cleared', async () => {
    await reachResultWithTx();

    const root = screen.getByTestId('pulsar-game-root');
    expect(root.getAttribute('data-settlement-tx')).toBe(TX_HASH);

    await act(async () => {
      fireEvent.click(screen.getByText('nextDuel'));
      await Promise.resolve();
    });

    expect(screen.getByTestId('pulsar-game-root').getAttribute('data-settlement-tx')).toBe('');
  });

  it('the previous match and session are cleared too', async () => {
    await reachResultWithTx();

    await act(async () => {
      fireEvent.click(screen.getByText('nextDuel'));
      await Promise.resolve();
    });

    // A stale match id would be reused by the next duel; a stale session would
    // authenticate it as the previous match.
    expect(localStorage.getItem('pulsar_active_ranked_match')).toBeNull();
  });
});
