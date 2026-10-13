/**
 * M27 closure — a challenge the target cannot discover is a duel that never
 * happens.
 *
 * The reservation was real but invisible: the challenged player only found out
 * by queueing for something else. The Lobby now asks the server who is waiting
 * for them and offers an Accept that carries the challenger's ADDRESS (which is
 * what makes the acceptance land in the reserved match).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, act, cleanup } from '@testing-library/react';
import React from 'react';

const ME = '0x' + '11'.repeat(20);
const CHALLENGER = '0x' + 'ab'.repeat(20);

const h = vi.hoisted(() => ({
  fetchPendingChallenges: vi.fn(),
  loadServerSession: vi.fn(),
}));

vi.mock('../lib/realWeb3', () => ({
  realWeb3Manager: {
    subscribeGlobalMatches: () => () => {},
  },
}));

vi.mock('../store/usePulsarStore', () => ({
  usePulsarStore: () => ({
    wallet: { connected: true, address: ME, balance: 100 },
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
  loadServerSession: () => h.loadServerSession(),
  fetchPendingChallenges: (...a: unknown[]) => h.fetchPendingChallenges(...(a as [])),
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

describe('challenge discovery (audit M27 closure)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    h.loadServerSession.mockReturnValue({ token: 't', address: ME });
    h.fetchPendingChallenges.mockResolvedValue({
      available: true,
      challenges: [{ matchId: 'm1', address: CHALLENGER, stake: 2 }],
    });
  });

  afterEach(() => {
    cleanup();
  });

  it('shows the waiting challenge and accepts it with the challenger address', async () => {
    const onNavigate = vi.fn();
    const onStartDuelWithOpponent = vi.fn();

    render(
      <LobbyPage onNavigate={onNavigate} onStartDuelWithOpponent={onStartDuelWithOpponent} />
    );

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const accept = await screen.findByTestId('pulsar-accept-challenge');
    await act(async () => {
      fireEvent.click(accept);
      await Promise.resolve();
    });

    // The address is what makes the acceptance land in the RESERVED match.
    expect(onStartDuelWithOpponent).toHaveBeenCalledWith(expect.any(String), 2, CHALLENGER);
    expect(onNavigate).toHaveBeenCalledWith(
      '/game/reaction',
      expect.any(String),
      2,
      undefined,
      CHALLENGER
    );
  });

  it('shows nothing when the server reports no challenges', async () => {
    h.fetchPendingChallenges.mockResolvedValue({ available: true, challenges: [] });

    render(<LobbyPage onNavigate={vi.fn()} />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.queryByTestId('pulsar-accept-challenge')).toBeNull();
  });
});
