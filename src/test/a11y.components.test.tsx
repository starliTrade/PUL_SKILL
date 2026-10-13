/**
 * axe sweep over the components (plan item 8.13).
 *
 * The phase-8 exit gate is "axe: zero critical/serious violations". Each case
 * renders the real component with the minimum mocks its own tests already use,
 * then asserts the sweep is clean.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, act } from '@testing-library/react';
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
  escrowStatus: () => ({ configured: true, escrowAddress: '0x' + 'ab'.repeat(20), message: '' }),
  // A non-zero credit so the card actually renders (it hides itself at zero).
  getPendingWithdrawal: vi.fn(async () => '1.96'),
  withdrawPending: vi.fn(),
}));

const storeState = vi.hoisted(() => ({
  identityLockedReason: '',
  wallet: { connected: false, address: '', balance: 0 },
  stats: { balance: 0, balanceUnknown: true },
  history: [] as unknown[],
}));

vi.mock('../store/usePulsarStore', () => ({
  usePulsarStore: () => ({ ...storeState }),
}));

import { EligibilityGate } from '../components/EligibilityGate';
import { AppHeader } from '../components/AppHeader';
import { FriendChallengeModal } from '../components/FriendChallengeModal';
import { IdentityLockBanner } from '../components/IdentityLockBanner';
import { DisputeReportButton } from '../components/DisputeReportButton';
import { DuelCertificateModal } from '../components/DuelCertificateModal';
import { PendingPayoutCard } from '../components/PendingPayoutCard';
import { BottomNav } from '../components/BottomNav';
import { LanguageSelector } from '../components/LanguageSelector';

async function expectClean(node: HTMLElement, label: string) {
  // A sweep over an EMPTY render passes trivially. Assert there is real markup
  // to audit, so a broken mock cannot turn this gate into a no-op.
  expect(node.querySelectorAll('*').length, `${label} rendered nothing to audit`).toBeGreaterThan(0);
  const found = await axeViolations(node);
  expect(found, `${label}\n${describeViolations(found)}`).toEqual([]);
}

describe('axe sweep — components (plan item 8.13)', () => {
  beforeEach(() => {
    localStorage.clear();
  });
  afterEach(() => {
    cleanup();
  });

  it('EligibilityGate', async () => {
    const { container } = render(<EligibilityGate />);
    await expectClean(container, 'EligibilityGate');
  });

  it('DuelCertificateModal (a settled duel)', async () => {
    const { container } = render(
      <DuelCertificateModal
        isOpen
        onClose={() => {}}
        match={{
          id: 'a'.repeat(32),
          game: 'reaction',
          result: 'win',
          entryFee: 1,
          prize: 1.96,
          opponentTime: 300,
          yourTime: 200,
          timestamp: Date.now(),
          hash: '0x' + 'cd'.repeat(32),
        }}
      />
    );
    await expectClean(container, 'DuelCertificateModal');
  });

  it('PendingPayoutCard', async () => {
    const { container } = render(<PendingPayoutCard address={'0x' + '11'.repeat(20)} />);
    // The card resolves its credit in an effect; let it land before auditing.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    await expectClean(container, 'PendingPayoutCard');
  });

  it('BottomNav', async () => {
    const { container } = render(<BottomNav currentPath="/lobby" onNavigate={() => {}} />);
    await expectClean(container, 'BottomNav');
  });

  it('LanguageSelector', async () => {
    const { container } = render(<LanguageSelector />);
    await expectClean(container, 'LanguageSelector');
  });

  it('AppHeader', async () => {
    const { container } = render(<AppHeader onNavigate={() => {}} />);
    await expectClean(container, 'AppHeader');
  });

  it('FriendChallengeModal (open)', async () => {
    const { container } = render(
      <FriendChallengeModal isOpen onClose={() => {}} selectedStake={1} onStartDuel={() => {}} />
    );
    await expectClean(container, 'FriendChallengeModal');
  });

  it('IdentityLockBanner (locked)', async () => {
    storeState.identityLockedReason = 'Finish your live match first.';
    const { container } = render(<IdentityLockBanner />);
    await expectClean(container, 'IdentityLockBanner');
    storeState.identityLockedReason = '';
  });

  it('DisputeReportButton', async () => {
    const { container } = render(
      <DisputeReportButton matchId={'a'.repeat(32)} address={'0x' + '11'.repeat(20)} />
    );
    await expectClean(container, 'DisputeReportButton');
  });
});
