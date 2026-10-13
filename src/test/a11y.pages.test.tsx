/**
 * axe sweep over the pages (plan item 8.13).
 *
 * The components are covered in `a11y.components.test.tsx`; this is the other
 * half of the exit gate — the assembled screens, where landmark, heading-order
 * and name problems actually surface.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import React from 'react';
import { axeViolations, describeViolations } from './a11y';

vi.mock('../i18n/LanguageContext', () => ({
  useLanguage: () => ({
    t: (key: string) => key,
    currentLanguage: 'en',
    langInfo: { code: 'en', name: 'English', nativeName: 'English', flag: '🇬🇧', dir: 'ltr' },
    setLanguage: vi.fn(),
  }),
}));

vi.mock('../lib/sound', () => ({
  sounds: {
    playClick: vi.fn(), playTick: vi.fn(), playGo: vi.fn(), playHit: vi.fn(),
    playWin: vi.fn(), playLoss: vi.fn(), playError: vi.fn(),
  },
}));

vi.mock('../lib/escrowFlow', () => ({
  escrowStatus: () => ({ configured: false, escrowAddress: '', message: '' }),
  getPendingWithdrawal: vi.fn(async () => '0'),
  withdrawPending: vi.fn(),
  getTokenDecimals: vi.fn(async () => 6),
}));

vi.mock('../lib/gameServerClient', () => ({
  gameServerConfigured: () => false,
  loadServerSession: () => null,
  fetchPendingChallenges: async () => ({ available: true, challenges: [] }),
}));

vi.mock('../lib/realWeb3', () => ({
  realWeb3Manager: {
    subscribeGlobalMatches: () => () => {},
    getAccount: () => ({ address: '', connected: false }),
    fetchGlobalLeaderboard: async () => [],
  },
}));

const store = vi.hoisted(() => ({
  wallet: { connected: false, address: '', balance: 0, playerId: 'Tester#1' },
  stats: { balance: 0, balanceUnknown: true, wins: 0, losses: 0, voids: 0, totalMatches: 0, xp: 0, level: 1 },
  // Audit 2026-10-13: an EMPTY history meant the history rows — the ones 8.3
  // converted and the ones that contain an explorer <a> — never rendered, so
  // the sweep could not see a nested-interactive violation in them.
  history: [
    {
      id: 'a'.repeat(32),
      game: 'reaction',
      result: 'win',
      entryFee: 1,
      prize: 1.96,
      opponentTime: 300,
      yourTime: 210,
      timestamp: 1750000000000,
      hash: '0x' + 'ab'.repeat(32),
    },
    {
      id: 'b'.repeat(32),
      game: 'reaction',
      result: 'loss',
      entryFee: 1,
      prize: 0,
      opponentTime: 200,
      yourTime: 260,
      timestamp: 1749990000000,
      hash: '',
    },
  ] as unknown[],
  leaderboard: [] as unknown[],
  refreshBalance: vi.fn(async () => undefined),
  updatePlayerTag: vi.fn(),
  checkUsernameAvailability: vi.fn(async () => ({ available: true, cleanTag: '' })),
  updateBenchmarkSpeed: vi.fn(),
  identityLockedReason: '',
}));

vi.mock('../store/usePulsarStore', () => ({ usePulsarStore: () => ({ ...store }) }));

vi.mock('../components/ConnectWallet', () => ({ ConnectWallet: () => null }));
vi.mock('../components/PulsarCosmicBackground', () => ({ PulsarCosmicBackground: () => null }));
vi.mock('../components/FriendChallengeModal', () => ({ FriendChallengeModal: () => null }));

import { HomePage } from '../pages/HomePage';
import { LegalPage } from '../pages/LegalPage';
import { DashboardPage } from '../pages/DashboardPage';
import { ProfilePage } from '../pages/ProfilePage';
import { LobbyPage } from '../pages/LobbyPage';

async function expectClean(node: HTMLElement, label: string) {
  // A sweep over an EMPTY render passes trivially. Assert there is real markup
  // to audit, so a broken mock cannot turn this gate into a no-op.
  expect(node.querySelectorAll('*').length, `${label} rendered nothing to audit`).toBeGreaterThan(0);
  const found = await axeViolations(node);
  expect(found, `${label}\n${describeViolations(found)}`).toEqual([]);
}

describe('axe sweep — pages (plan item 8.13)', () => {
  beforeEach(() => {
    localStorage.clear();
  });
  afterEach(() => {
    cleanup();
  });

  it('HomePage', async () => {
    const { container } = render(<HomePage onNavigate={() => {}} />);
    await expectClean(container, 'HomePage');
  });

  it('LegalPage', async () => {
    const { container } = render(<LegalPage onNavigate={() => {}} />);
    await expectClean(container, 'LegalPage');
  });

  it('DashboardPage (with history rows rendered)', async () => {
    const { container } = render(<DashboardPage onNavigate={() => {}} />);
    // Prove the rows actually rendered — otherwise this sweep is auditing an
    // empty list and cannot see a defect inside a row. The row's summary is the
    // ARIA button carrying `aria-expanded`.
    const rows = container.querySelectorAll('[role="button"][aria-expanded]');
    expect(rows.length, 'the history rows did not render').toBe(2);
    await expectClean(container, 'DashboardPage');
  });

  it('ProfilePage', async () => {
    const { container } = render(<ProfilePage onNavigate={() => {}} />);
    await expectClean(container, 'ProfilePage');
  });

  it('LobbyPage', async () => {
    const { container } = render(<LobbyPage onNavigate={() => {}} />);
    await expectClean(container, 'LobbyPage');
  });
});
