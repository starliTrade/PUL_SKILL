/**
 * M29 — every timer the page starts must be cleaned up.
 *
 * `processVerification` created its progress interval in a LOCAL variable, so
 * the unmount effect could not clear it: navigating away mid-round left an
 * interval ticking and calling `setState` on an unmounted component.
 * `handleEarlyClick` was worse — a bare `setTimeout` with no ref at all, which
 * fires `startWaitingPhase()` 1.4s later even if the player has left the page.
 *
 * The test counts what the page creates and what it clears, which is precise
 * and does not depend on React warning about post-unmount updates (it no longer
 * does).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react';
import React from 'react';

const submitRoundResult = vi.fn(async () => ({ accepted: true, reason: '' }));
const getMatch = vi.fn();
const ensureSession = vi.fn(async () => ({ token: 't', address: '0x' + '11'.repeat(20) }));

vi.mock('../lib/gameServerClient', () => ({
  gameServerConfigured: () => true,
  ensureSession: (...a: unknown[]) => ensureSession(...(a as [])),
  queueForMatch: vi.fn(async () => ({ status: 'active' })),
  commitRound: vi.fn(async () => undefined),
  revealRoundTarget: vi.fn(async () => ({ targetMs: 100, resultProof: 'proof' })),
  submitRoundResult: (...a: unknown[]) => submitRoundResult(...(a as [])),
  settleMatch: vi.fn(async () => ({ status: 'settled', winner: '0x' + '11'.repeat(20) })),
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
  settleDuel: vi.fn(async () => '0x' + 'cd'.repeat(32)),
  refundTimeoutMatch: vi.fn(),
  escrowStatus: () => ({ configured: true, escrowAddress: '0x' + 'ab'.repeat(20), message: '' }),
  approveUsdt: vi.fn(),
  createDuel: vi.fn(),
  joinDuel: vi.fn(),
  getDuelState: vi.fn(),
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

function activeView() {
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
      { index: 0, committed: false, targetRevealed: false, submitted: false, valid: false, rejectReason: '' },
      { index: 1, committed: false, targetRevealed: false, submitted: false, valid: false, rejectReason: '' },
      { index: 2, committed: false, targetRevealed: false, submitted: false, valid: false, rejectReason: '' },
    ],
    myTimes: {},
    opponentTimes: {},
    opponentSubmitted: 0,
  };
}

describe('timer cleanup (audit M29)', () => {
  let createdIntervals: unknown[];
  let clearedIntervals: unknown[];
  let createdTimeouts: unknown[];
  let clearedTimeouts: unknown[];

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    getMatch.mockResolvedValue(activeView());

    createdIntervals = [];
    clearedIntervals = [];
    createdTimeouts = [];
    clearedTimeouts = [];

    const realSetInterval = globalThis.setInterval;
    const realClearInterval = globalThis.clearInterval;
    const realSetTimeout = globalThis.setTimeout;
    const realClearTimeout = globalThis.clearTimeout;

    vi.spyOn(globalThis, 'setInterval').mockImplementation((fn: never, ms?: never) => {
      const id = realSetInterval(fn, ms);
      createdIntervals.push(id);
      return id;
    });
    vi.spyOn(globalThis, 'clearInterval').mockImplementation((id: never) => {
      clearedIntervals.push(id);
      return realClearInterval(id);
    });
    vi.spyOn(globalThis, 'setTimeout').mockImplementation((fn: never, ms?: never) => {
      const id = realSetTimeout(fn, ms);
      createdTimeouts.push(id);
      return id;
    });
    vi.spyOn(globalThis, 'clearTimeout').mockImplementation((id: never) => {
      clearedTimeouts.push(id);
      return realClearTimeout(id);
    });
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  /** Drive the page into a round, where the progress interval is running. */
  async function reachRound() {
    const { unmount } = render(<ReactionGamePage onNavigate={vi.fn()} stakeAmount={1} />);

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

    // Real timers: the round's target delay is 100ms in the mock, so waiting
    // for it is enough and avoids fighting the fake-timer API.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 250));
    });
    return { unmount };
  }

  it('unmounting mid-round leaves no interval running', async () => {
    const { unmount } = await reachRound();

    const target = screen.queryByTestId('pulsar-target');
    if (target) {
      // Tapping starts processVerification, which creates the progress interval.
      await act(async () => {
        fireEvent.click(target);
        await Promise.resolve();
      });
    }

    const beforeUnmount = createdIntervals.length;
    unmount();

    const stillRunning = createdIntervals.filter((id) => !clearedIntervals.includes(id));
    expect(stillRunning).toHaveLength(0);
    expect(beforeUnmount).toBeGreaterThan(0);
  });
});
