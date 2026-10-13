/**
 * M39 — the certificate must show the REAL on-chain proof, not always
 * "NOT ON-CHAIN".
 *
 * `DuelCertificateModal` already derives `isOnChain` honestly from
 * `match.hash` (a 64-hex tx hash). The bug was upstream: the page built the
 * certificate's match object and the history record WITHOUT a `hash`, so a
 * settled duel's certificate could never render the on-chain proof its copy
 * promised. This test drives a WIN through the real page, opens the real
 * certificate, and asserts the settlement tx is shown.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react';
import React from 'react';

const MATCH_ID = 'a'.repeat(32);
const ME = '0x' + '11'.repeat(20);
const OPPONENT = '0x' + '22'.repeat(20);
const TX_HASH = '0x' + 'cd'.repeat(32);

const settleMatch = vi.fn(async () => ({
  status: 'settled',
  matchId: MATCH_ID,
  winner: ME,
  winnerTimeMs: 200,
  loserTimeMs: 300,
  serverNonce: 1,
  deadline: Math.floor(Date.now() / 1000) + 600,
  oracleAddress: '0x' + 'ef'.repeat(20),
  signature: '0x' + 'ab'.repeat(65),
  validatedTimes: {},
}));
const getMatch = vi.fn();
const recordMatch = vi.fn(async (_match?: { hash?: string }) => ({ totalXP: 0, levelUp: false }));
const settleDuel = vi.fn(async () => TX_HASH);
const ensureSession = vi.fn(async () => ({ token: 't', address: ME }));

vi.mock('../lib/gameServerClient', () => ({
  gameServerConfigured: () => true,
  ensureSession: (...a: unknown[]) => ensureSession(...(a as [])),
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
    recordMatch: (...a: unknown[]) => recordMatch(...(a as [])),
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
  settleDuel: (...a: unknown[]) => settleDuel(...(a as [])),
  refundTimeoutMatch: vi.fn(),
  escrowStatus: () => ({ configured: true, escrowAddress: '0x' + 'ab'.repeat(20), message: '' }),
  approveUsdt: vi.fn(),
  createDuel: vi.fn(),
  joinDuel: vi.fn(),
  getDuelState: vi.fn(),
  findSettlementTx: vi.fn(async () => ''),
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
vi.mock('../components/PulsarCosmicBackground', () => ({ PulsarCosmicBackground: () => null }));

vi.mock('../i18n/LanguageContext', () => ({
  useLanguage: () => ({ t: (key: string) => key, currentLanguage: 'en', setLanguage: vi.fn() }),
}));

import { ReactionGamePage } from './ReactionGamePage';

/** A decided match the player has WON 2-0. */
function wonView() {
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
    myTimes: { '0': 200, '1': 210 },
    opponentTimes: { '0': 300, '1': 310 },
    opponentSubmitted: 2,
  };
}

async function driveToResult() {
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
    expect(screen.getByText('View Cryptographic Certificate & Proof')).toBeTruthy();
  }, { timeout: 3000 });
}

describe('duel certificate proof (audit M39)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    getMatch.mockResolvedValue(wonView());
    settleDuel.mockResolvedValue(TX_HASH);
  });

  afterEach(() => {
    cleanup();
  });

  it('records the settlement tx hash against the match history', async () => {
    await driveToResult();

    expect(recordMatch).toHaveBeenCalled();
    const recorded = recordMatch.mock.calls[0][0] as { hash?: string } | undefined;
    expect(recorded?.hash).toBe(TX_HASH);
  });

  it('shows the on-chain settlement in the certificate, not "NOT ON-CHAIN"', async () => {
    await driveToResult();

    await act(async () => {
      fireEvent.click(screen.getByText('View Cryptographic Certificate & Proof'));
      await Promise.resolve();
    });

    // Audit 8.9: the badge is translated now, and this file's i18n mock returns
    // the key — so the assertion is on the key.
    expect(screen.getByText('certOnChainSettled')).toBeTruthy();
    expect(screen.queryByText('certLocalResult')).toBeNull();
    // The real tx hash is displayed (truncated) and linked to the explorer.
    expect(screen.getByText(`${TX_HASH.slice(0, 10)}...${TX_HASH.slice(-8)}`)).toBeTruthy();
  });
});
