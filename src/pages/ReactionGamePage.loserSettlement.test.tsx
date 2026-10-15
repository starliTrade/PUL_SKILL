/**
 * M37 — settlement is permissionless on-chain, so the client must not gate it
 * behind "am I the winner".
 *
 * `settleDuel(proof)` pays `proof.winner` regardless of `msg.sender`; the
 * contract only requires that the winner be a participant. The page, however,
 * built and submitted the proof only inside `if (iWon)`. So if the winner's tab
 * closed before settling, the pot stayed locked until the refund horizon — and
 * the loser had no path to force settlement. Both sides must release it.
 *
 * This test drives the real page into a LOST decided match and asserts the
 * on-chain proof is still submitted (and that the loser does NOT try to claim,
 * which audit M11 restricts to the winner).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react';
import React from 'react';

const MATCH_ID = 'a'.repeat(32);
const ME = '0x' + '11'.repeat(20);
const OPPONENT = '0x' + '22'.repeat(20);

const settleMatch = vi.fn(async () => ({
  status: 'settled',
  matchId: MATCH_ID,
  // The OTHER player won — this is the loser's client.
  winner: OPPONENT,
  winnerTimeMs: 200,
  loserTimeMs: 300,
  serverNonce: 1,
  deadline: Math.floor(Date.now() / 1000) + 600,
  oracleAddress: '0x' + 'ef'.repeat(20),
  signature: '0x' + 'ab'.repeat(65),
  validatedTimes: {},
}));
const getMatch = vi.fn();
const claimMatch = vi.fn(async () => ({ ok: true, onChainProof: true }));
const settleDuel = vi.fn(async () => '0x' + 'cd'.repeat(32));
const findSettlementTx = vi.fn(async () => '');
const getDuelState = vi.fn(async () => ({
  status: 2, // Active — the winner has NOT settled yet.
  player1: ME,
  player2: OPPONENT,
  stakeAmount: 0n,
  totalPool: 0n,
  winner: '',
}));
const ensureSession = vi.fn(async () => ({ token: 't', address: ME }));

vi.mock('../lib/gameServerClient', () => ({
  gameServerConfigured: () => true,
  ensureSession: (...a: unknown[]) => ensureSession(...(a as [])),
  // Plan item 11.3/G2: the game page records the eligibility attestation
  confirmEligibility: vi.fn(async () => undefined),
  measureServerRttMs: async () => 20,
  queueForMatch: vi.fn(async () => ({ status: 'active' })),
  commitRound: vi.fn(async () => undefined),
  revealRoundTarget: vi.fn(async () => ({ targetMs: 100, resultProof: 'proof' })),
  submitRoundResult: vi.fn(async () => ({ accepted: true, reason: '' })),
  settleMatch: (...a: unknown[]) => settleMatch(...(a as [])),
  claimMatch: (...a: unknown[]) => claimMatch(...(a as [])),
  getMatch: (...a: unknown[]) => getMatch(...(a as [])),
  matchIdToBytes32: async () => '0x' + '00'.repeat(32),
}));

vi.mock('../store/usePulsarStore', () => ({
  usePulsarStore: () => ({
    wallet: {
      address: ME,
      fullAddress: ME,
      connected: true,
      balanceUSDT: 100,
      balanceUnknown: false,
    },
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
    recordMatch: vi.fn(),
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
  },
}));

vi.mock('canvas-confetti', () => ({ default: vi.fn() }));

vi.mock('../lib/escrowFlow', () => ({
  settleDuel: (...a: unknown[]) => settleDuel(...(a as [])),
  refundTimeoutMatch: vi.fn(),
  escrowStatus: () => ({ configured: true, escrowAddress: '0x' + 'ab'.repeat(20), message: '' }),
  approveUsdt: vi.fn(),
  createDuel: vi.fn(),
  joinDuel: vi.fn(),
  getDuelState: (...a: unknown[]) => getDuelState(...(a as [])),
  findSettlementTx: (...a: unknown[]) => findSettlementTx(...(a as [])),
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

/** A decided match the player has LOST 0-2 — the opponent is the winner. */
function lostView() {
  return {
    matchId: MATCH_ID,
    stake: 1,
    status: 'active',
    winner: '',
    createdAt: 0,
    rounds: 3,
    me: ME,
    opponentJoined: true,
    opponent: OPPONENT,
    youAreCreator: true,
    youAreJoiner: false,
    myRounds: [
      { index: 0, committed: true, targetRevealed: true, submitted: true, valid: true, rejectReason: '' },
      { index: 1, committed: true, targetRevealed: true, submitted: true, valid: true, rejectReason: '' },
      { index: 2, committed: false, targetRevealed: false, submitted: false, valid: false, rejectReason: '' },
    ],
    // Slower than the opponent in both rounds → opponent wins 2-0.
    myTimes: { '0': 300, '1': 310 },
    opponentTimes: { '0': 200, '1': 210 },
    opponentSubmitted: 2,
  };
}

describe('loser-side settlement (audit M37)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    getMatch.mockResolvedValue(lostView());
    settleDuel.mockResolvedValue('0x' + 'cd'.repeat(32));
    getDuelState.mockResolvedValue({
      status: 2,
      player1: ME,
      player2: OPPONENT,
      stakeAmount: 0n,
      totalPool: 0n,
      winner: '',
    });
  });

  afterEach(() => {
    cleanup();
  });

  it('the loser also submits the oracle proof so the pot is released', async () => {
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
      expect(settleDuel).toHaveBeenCalled();
    }, { timeout: 3000 });

    // The loser releases the pot but must NOT claim — audit M11 reserves the
    // claim to the winner.
    expect(claimMatch).not.toHaveBeenCalled();
  });

  it('does not spend the loser gas when the winner already settled on-chain', async () => {
    // status 3 = Settled: the winner got there first, so there is nothing to
    // release. Submitting anyway would revert ("Signature already used") and
    // burn the loser's gas.
    getDuelState.mockResolvedValue({
      status: 3,
      player1: ME,
      player2: OPPONENT,
      stakeAmount: 0n,
      totalPool: 0n,
      winner: OPPONENT,
    });

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
      expect(getDuelState).toHaveBeenCalled();
    }, { timeout: 3000 });

    expect(settleDuel).not.toHaveBeenCalled();
  });

  it('reads the settlement tx back from the chain when the winner settled first', async () => {
    // The loser submitted nothing, so it has no tx hash of its own — and its
    // certificate used to claim "NOT ON-CHAIN" for a duel that IS settled.
    getDuelState.mockResolvedValue({
      status: 3,
      player1: ME,
      player2: OPPONENT,
      stakeAmount: 0n,
      totalPool: 0n,
      winner: OPPONENT,
    });
    const settledTx = '0x' + 'ee'.repeat(32);
    findSettlementTx.mockResolvedValue(settledTx);

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
      expect(findSettlementTx).toHaveBeenCalled();
    }, { timeout: 3000 });

    // The certificate's proof comes from the chain, not from a local guess.
    await vi.waitFor(() => {
      expect(screen.getByTestId('pulsar-game-root').getAttribute('data-settlement-tx')).toBe(settledTx);
    }, { timeout: 3000 });
    expect(settleDuel).not.toHaveBeenCalled();
  });
});
