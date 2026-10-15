/**
 * M27 — the game page must carry the challenged address into matchmaking.
 *
 * The friend-challenge flow navigated to the game page with the friend's NAME
 * only, and the page queued without naming anyone. Even with a server that can
 * reserve a match, the reservation never happened because the address was
 * dropped at the page boundary.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react';
import React from 'react';

const ME = '0x' + '11'.repeat(20);
const OPPONENT = '0x' + 'ab'.repeat(20);

const queueForMatch = vi.fn(async () => ({ matchId: 'm1', status: 'active', stake: 1 }));

vi.mock('../lib/gameServerClient', () => ({
  gameServerConfigured: () => true,
  ensureSession: vi.fn(async () => ({ token: 't', address: ME })),
  // Plan item 11.3/G2: the game page records the eligibility attestation
  confirmEligibility: vi.fn(async () => undefined),
  measureServerRttMs: async () => 20,
  queueForMatch: (...a: unknown[]) => queueForMatch(...(a as [])),
  commitRound: vi.fn(async () => undefined),
  revealRoundTarget: vi.fn(async () => ({ targetMs: 100, resultProof: 'proof' })),
  submitRoundResult: vi.fn(async () => ({ accepted: true, reason: '' })),
  settleMatch: vi.fn(async () => ({ status: 'settled' })),
  claimMatch: vi.fn(async () => ({ ok: true, onChainProof: true })),
  getMatch: vi.fn(async () => ({ matchId: 'm1', status: 'active', stake: 1, me: ME })),
  matchIdToBytes32: async () => '0x' + '00'.repeat(32),
}));

vi.mock('../store/usePulsarStore', () => ({
  usePulsarStore: () => ({
    wallet: { address: ME, fullAddress: ME, connected: true, balanceUSDT: 100, balanceUnknown: false },
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
    playClick: vi.fn(),
  },
}));

vi.mock('canvas-confetti', () => ({ default: vi.fn() }));

vi.mock('../lib/escrowFlow', () => ({
  settleDuel: vi.fn(async () => '0x' + 'cd'.repeat(32)),
  refundTimeoutMatch: vi.fn(),
  escrowStatus: () => ({ configured: true, escrowAddress: '0x' + 'ab'.repeat(20), message: '' }),
  approveUsdt: vi.fn(async () => '0x' + 'aa'.repeat(32)),
  createDuel: vi.fn(async () => '0x' + 'bb'.repeat(32)),
  joinDuel: vi.fn(async () => '0x' + 'cc'.repeat(32)),
  getDuelState: vi.fn(async () => ({ status: 2, player1: ME, player2: OPPONENT, stakeAmount: 0n, totalPool: 0n, winner: '' })),
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

describe('friend challenge wiring (audit M27)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  afterEach(() => {
    cleanup();
  });

  it('queues with the challenged address when the page is opened as a challenge', async () => {
    render(
      <ReactionGamePage onNavigate={vi.fn()} stakeAmount={1} challengeOpponent={OPPONENT} />
    );

    await act(async () => {
      fireEvent.click(screen.getByTestId('pulsar-verify-node'));
      await Promise.resolve();
      await Promise.resolve();
    });

    await vi.waitFor(() => {
      expect(queueForMatch).toHaveBeenCalled();
    }, { timeout: 3000 });

    const args = queueForMatch.mock.calls[0] as unknown[];
    expect(args[3]).toBe(OPPONENT);
  });

  it('queues without a target for an ordinary duel', async () => {
    render(<ReactionGamePage onNavigate={vi.fn()} stakeAmount={1} />);

    await act(async () => {
      fireEvent.click(screen.getByTestId('pulsar-verify-node'));
      await Promise.resolve();
      await Promise.resolve();
    });

    await vi.waitFor(() => {
      expect(queueForMatch).toHaveBeenCalled();
    }, { timeout: 3000 });

    const args = queueForMatch.mock.calls[0] as unknown[];
    expect(args[3]).toBeUndefined();
  });
});
