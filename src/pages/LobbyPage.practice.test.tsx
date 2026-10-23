/**
 * Audit L-12 — a training bot must not be presented as an opponent.
 *
 * The practice flow picks a name from a 12-entry `BOT_NAMES` list with
 * `Math.random()` and the overlay said "OPPONENT READY" / "Starting duel vs
 * ShadowStrike…". Nothing was named as a bot in that overlay (the game screen
 * disclosed it afterwards, which is too late to matter), and a player who
 * screenshots the lobby has a "match" against a person who does not exist.
 *
 * The overlay is practice-only: `handleStartMatchmaking` returns early for real
 * mode, where the SERVER does the matchmaking. So its copy can — and now does —
 * name the terms: a training bot, no stake, no payout, no ranking.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, act, cleanup, fireEvent } from '@testing-library/react';
import React from 'react';

vi.mock('../lib/realWeb3', () => ({
  realWeb3Manager: {
    subscribeGlobalMatches: () => () => {},
    fetchGlobalLeaderboard: async () => [],
    getSavedFriendsList: () => [],
    refreshSavedFriends: async () => [],
  },
}));

vi.mock('../store/usePulsarStore', () => ({
  usePulsarStore: () => ({
    wallet: { connected: true, address: '0x' + '11'.repeat(20), balance: 100 },
    stats: { balance: 100, balanceUnknown: false, wins: 0, losses: 0, totalMatches: 0 },
    refreshBalance: vi.fn(async () => undefined),
    history: [],
  }),
}));

vi.mock('../lib/escrowFlow', () => ({
  escrowStatus: () => ({ configured: true, escrowAddress: '0x' + 'ab'.repeat(20), message: '' }),
}));

vi.mock('../lib/gameServerClient', () => ({
  gameServerConfigured: () => true,
  loadServerSession: () => null,
  fetchPendingChallenges: async () => ({ available: true, challenges: [] }),
}));

vi.mock('../lib/sound', () => ({
  sounds: {
    playClick: vi.fn(),
    playError: vi.fn(),
    playGo: vi.fn(),
    playWin: vi.fn(),
    playLoss: vi.fn(),
    playHit: vi.fn(),
    playTick: vi.fn(),
    playMatchFound: vi.fn(),
  },
}));

vi.mock('../i18n/LanguageContext', () => ({
  useLanguage: () => ({ t: (key: string) => key, currentLanguage: 'en', setLanguage: vi.fn() }),
}));

vi.mock('../components/AppHeader', () => ({ AppHeader: () => null }));
vi.mock('../components/ConnectWallet', () => ({ ConnectWallet: () => null }));
vi.mock('../components/PulsarCosmicBackground', () => ({ PulsarCosmicBackground: () => null }));
vi.mock('../components/FriendChallengeModal', () => ({ FriendChallengeModal: () => null }));

import { LobbyPage } from './LobbyPage';

describe('practice matchmaking is not a fake search for a person (L-12)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  function enterPractice() {
    render(<LobbyPage onNavigate={vi.fn()} />);
    fireEvent.click(screen.getByText('modePractice'));
    fireEvent.click(screen.getByText('startPracticeBtn'));
  }

  it('says the opponent is a bot, before the "match" starts', () => {
    enterPractice();
    expect(screen.getByTestId('practice-bot-notice')).toBeTruthy();
  });

  it('never claims a real opponent or an escrow lock', () => {
    enterPractice();
    const overlay = document.body.textContent ?? '';
    expect(overlay).not.toContain('opponentSecured');
    expect(overlay).not.toContain('lockingEscrowAgainst');
  });

  it('uses practice-specific wording once the partner is chosen', () => {
    enterPractice();
    act(() => {
      vi.advanceTimersByTime(3300); // 3.2s to the match, then the 1.5s handoff
    });
    expect(screen.getByText('practicePartnerReady')).toBeTruthy();
    // …and the terms are still on screen next to it.
    expect(screen.getByTestId('practice-bot-notice')).toBeTruthy();
  });
});
