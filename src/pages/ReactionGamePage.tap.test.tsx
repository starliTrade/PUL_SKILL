/**
 * C4 regression — one tap must submit exactly one result.
 *
 * Audit C4: the action-phase root div has `onTouchEnd={handleTouchEnd}` and the
 * target button has `onClick={handleTargetHit}`. A touch tap fires BOTH
 * (touchend bubbles to the root, then the browser synthesises a click on the
 * button), and `e.stopPropagation()` inside the click handler cannot cancel a
 * touchend that already ran. Both closures see `phase === 'action'`, so both
 * call `processVerification`.
 *
 * The second call hits a 409 from the server ("Result already submitted"),
 * which the catch block turns into `outcome: 'void'` + `phase: 'bot-detected'`
 * — so every touch player could lose a match to a browser event quirk, with
 * the prize going unclaimed.
 *
 * This test drives the REAL page through the real phases and fires the real
 * event pair, counting submissions.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react';
import React from 'react';

const submitRoundResult = vi.fn(async () => ({ accepted: true, reason: '' }));
const getMatch = vi.fn();
const ensureSession = vi.fn(async () => ({ token: 't', address: '0x' + '11'.repeat(20) }));
const commitRound = vi.fn(async () => undefined);
const revealRoundTarget = vi.fn(async () => ({ targetMs: 100, resultProof: 'proof' }));

vi.mock('../lib/gameServerClient', () => ({
  gameServerConfigured: () => true,
  ensureSession: (...a: unknown[]) => ensureSession(...(a as [])),
  // Audit H1: the submit path measures the round trip.
  measureServerRttMs: async () => 20,
  queueForMatch: vi.fn(async () => ({ status: 'active' })),
  commitRound: (...a: unknown[]) => commitRound(...(a as [])),
  revealRoundTarget: (...a: unknown[]) => revealRoundTarget(...(a as [])),
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
  settleDuel: vi.fn(),
  refundTimeoutMatch: vi.fn(),
  escrowStatus: () => ({ configured: true, escrowAddress: '0x' + 'ab'.repeat(20), message: '' }),
  approveUsdt: vi.fn(),
  createDuel: vi.fn(),
  joinDuel: vi.fn(),
  getDuelState: vi.fn(),
  findSettlementTx: vi.fn(async () => ''),
}));

vi.mock('../lib/monitoring', () => ({ reportError: vi.fn() }));

// The real isEscrowConfigured() reads VITE_* env, which is unset under vitest,
// so the page would refuse the staked flow before ever reaching a round.
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
const MY_ADDRESS = '0x' + '11'.repeat(20);

function activeView(overrides: Record<string, unknown> = {}) {
  return {
    matchId: MATCH_ID,
    stake: 1,
    status: 'active',
    winner: '',
    createdAt: 0,
    rounds: 3,
    me: MY_ADDRESS,
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
    ...overrides,
  };
}

/** Drive the page from mount to the action phase, where the target is live. */
async function reachActionPhase() {
  getMatch.mockResolvedValue(activeView());

  const { container } = render(<ReactionGamePage onNavigate={vi.fn()} stakeAmount={1} />);

  // Let the mount effects settle FIRST. `persistActiveMatch(null)` runs on mount
  // and REMOVES the persisted match, so seeding localStorage before the render
  // would be wiped before the verify tap ever happens.
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });

  localStorage.setItem(
    'pulsar_active_ranked_match',
    JSON.stringify({ matchId: MATCH_ID, stake: 1 })
  );

  // The page opens on the human-verify gate; the staked flow starts on that tap.
  await act(async () => {
    fireEvent.click(screen.getByTestId('pulsar-verify-node'));
    await Promise.resolve();
    await Promise.resolve();
  });

  // mount -> recoverServerMatch -> phase 'ready'
  for (let i = 0; i < 10 && !screen.queryByText('focusEyes'); i++) {
    await act(async () => {
      await Promise.resolve();
    });
  }

  // ready countdown (3 x 700ms) -> startWaitingPhase -> commit + reveal -> targetMs
  // The server branch is async, so advance in slices and flush microtasks
  // between them rather than guessing one exact duration.
  for (let i = 0; i < 40; i++) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
    });
    if (screen.queryByTestId('pulsar-target')) break;
  }

  const target = screen.queryByTestId('pulsar-target');
  if (!target) {
    throw new Error(
      `never reached the action phase; commitRound=${commitRound.mock.calls.length} ` +
        `reveal=${revealRoundTarget.mock.calls.length} ` +
        `ensureSession=${ensureSession.mock.calls.length} getMatch=${getMatch.mock.calls.length} ` +
        `body=${(document.body.textContent || '').slice(0, 300)}`
    );
  }
  // The touch handlers live on the page's OWN root div, not on the render
  // container — dispatching touchend on the container never reaches them, which
  // made this test pass without exercising the bug at all.
  const root = container.firstElementChild as HTMLElement;
  if (!root) throw new Error('page root not found');
  return { target, root, container };
}

describe('one tap submits exactly one round result (audit C4)', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.clearAllMocks();
    localStorage.clear();
    getMatch.mockResolvedValue(activeView());
    submitRoundResult.mockResolvedValue({ accepted: true, reason: '' });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it('reaches the action phase with a live target', async () => {
    const { target } = await reachActionPhase();
    expect(target).toBeTruthy();
  });

  it('a touch tap (touchend + synthetic click) submits ONCE', async () => {
    const { target, root } = await reachActionPhase();

    await act(async () => {
      // What a real finger does on a touch screen, in order.
      fireEvent.touchStart(root, { touches: [{ clientX: 10, clientY: 10 }] });
      fireEvent.touchEnd(root, { changedTouches: [{ clientX: 10, clientY: 10 }] });
      fireEvent.click(target);
      await Promise.resolve();
    });

    expect(submitRoundResult).toHaveBeenCalledTimes(1);
  });

  it('a mouse click alone submits once', async () => {
    const { target } = await reachActionPhase();

    await act(async () => {
      fireEvent.click(target);
      await Promise.resolve();
    });

    expect(submitRoundResult).toHaveBeenCalledTimes(1);
  });

  it('a double tap cannot burn the round into a void match', async () => {
    const { target, root } = await reachActionPhase();

    await act(async () => {
      fireEvent.touchEnd(root, { changedTouches: [{ clientX: 5, clientY: 5 }] });
      fireEvent.click(target);
      fireEvent.click(target);
      await Promise.resolve();
    });

    expect(submitRoundResult).toHaveBeenCalledTimes(1);
  });
});
