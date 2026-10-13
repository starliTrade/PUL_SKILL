/**
 * M42 — the "live arena feed" must clear when the arena empties.
 *
 * `subscribeGlobalMatches` correctly delivers an empty list when there are no
 * recent real-stake duels. The Lobby consumer guarded the update with
 * `if (matches.length > 0)`, so an empty snapshot was ignored and the previous
 * entries stayed on screen as if they were live — forever. An empty feed is a
 * fact, not a missing value.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, act, cleanup } from '@testing-library/react';
import React from 'react';

const feed = vi.hoisted(() => ({
  callback: null as null | ((matches: unknown[]) => void),
}));

vi.mock('../lib/realWeb3', () => ({
  realWeb3Manager: {
    subscribeGlobalMatches: (cb: (matches: unknown[]) => void) => {
      feed.callback = cb;
      return () => {};
    },
  },
}));

vi.mock('../store/usePulsarStore', () => ({
  usePulsarStore: () => ({
    wallet: { connected: true, address: '0x' + '11'.repeat(20), balance: 100 },
    stats: { balance: 100, balanceUnknown: false, wins: 0, losses: 0, totalMatches: 0 },
    refreshBalance: vi.fn(async () => undefined),
    // No local history: the feed must reflect the SERVER, not the player.
    history: [],
  }),
}));

vi.mock('../lib/escrowFlow', () => ({
  escrowStatus: () => ({ configured: true, escrowAddress: '0x' + 'ab'.repeat(20), message: '' }),
}));

vi.mock('../lib/gameServerClient', () => ({
  gameServerConfigured: () => true,
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

const LIVE_MATCH = {
  id: 'm1',
  game: 'reaction',
  result: 'win',
  entryFee: 5,
  prize: 9.8,
  opponentTime: 300,
  yourTime: 200,
  timestamp: Date.now(),
  opponentName: 'GhostOfArena',
};

describe('live arena feed (audit M42)', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    feed.callback = null;
  });

  afterEach(() => {
    cleanup();
  });

  it('clears stale entries when the server reports an empty arena', async () => {
    render(<LobbyPage onNavigate={vi.fn()} />);
    await act(async () => {
      await Promise.resolve();
    });
    expect(feed.callback).toBeTypeOf('function');

    // A live match arrives and is shown.
    await act(async () => {
      feed.callback?.([LIVE_MATCH]);
    });
    expect(screen.getByText('GhostOfArena')).toBeTruthy();

    // The arena empties — the previous entry must NOT linger.
    await act(async () => {
      feed.callback?.([]);
    });
    expect(screen.queryByText('GhostOfArena')).toBeNull();
  });
});
