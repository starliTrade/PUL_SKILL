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
  revealRoundTarget: vi.fn(async () => ({ targetMs: 5000, resultProof: 'proof' })),
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
  let createdTimeouts: unknown[];
  let clearedTimeouts: unknown[];

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    getMatch.mockResolvedValue(activeView());

    createdTimeouts = [];
    clearedTimeouts = [];

    const realSetTimeout = globalThis.setTimeout;
    const realClearTimeout = globalThis.clearTimeout;

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

  /**
   * Reach the WAITING phase — the window between the countdown and the target,
   * where an early click arms the 1400ms restart timer.
   */
  async function reachWaiting() {
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

    // The ready countdown is 3 x 700ms; the mock's target delay is 5s, so the
    // waiting window stays open long enough to click inside it.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 2600));
    });
    return { unmount };
  }

  it('an early click arms a restart timer', async () => {
    await reachWaiting();
    expect(screen.queryByTestId('pulsar-waiting')).not.toBeNull();

    const before = createdTimeouts.length;
    await act(async () => {
      fireEvent.click(screen.getByTestId('pulsar-waiting'));
      await Promise.resolve();
    });

    expect(createdTimeouts.length).toBeGreaterThan(before);
  });

  it('unmounting after an early click cancels the pending restart', async () => {
    const { unmount } = await reachWaiting();

    const before = createdTimeouts.length;
    await act(async () => {
      fireEvent.click(screen.getByTestId('pulsar-waiting'));
      await Promise.resolve();
    });

    // Only the timers armed from here belong to this assertion; the page is not
    // the only thing in the process calling setTimeout.
    const armed = createdTimeouts.slice(before);
    expect(armed.length).toBeGreaterThan(0);

    unmount();

    const stillPending = armed.filter((id) => !clearedTimeouts.includes(id));
    expect(stillPending).toHaveLength(0);
  });
});
