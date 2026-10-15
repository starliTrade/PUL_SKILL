/**
 * Rollback with the escrow unset (plan item 11.2).
 *
 * The documented rollback is `VITE_ESCROW_ADDRESS` unset. The property that has
 * to hold is: **staked play is refused, and free play is untouched.** A rollback
 * that leaves players entering a flow that cannot finish is not a rollback — it
 * is an outage with a friendlier name.
 *
 * Audit 2026-10-15: I first recorded this as a gap — "the lobby lets a player
 * enter a staked duel and only refuses at the deposit step". That was WRONG, and
 * I found out by reading `handleStartMatchmaking` before changing it: the guard
 * was already the first thing it does, via `escrowStatus().configured`. The
 * lesson is the one this project keeps teaching — check before you add.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, cleanup, screen, fireEvent, waitFor } from '@testing-library/react';
import React from 'react';

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
    playWin: vi.fn(), playLoss: vi.fn(), playError: vi.fn(), playMatchFound: vi.fn(),
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

// THE CONDITION UNDER TEST: the escrow is unset. This is the rollback, and the
// lobby already refuses it — `escrowStatus()` (mocked above) is the single
// source of truth for "is real-money play wired up", and `handleStartMatchmaking`
// checks it before anything else. This test PINS that behaviour so a future
// change cannot quietly remove it.

import { LobbyPage } from '../pages/LobbyPage';

const navigate = vi.fn();

beforeEach(() => navigate.mockClear());
afterEach(() => cleanup());

describe('rollback: the escrow is unset', () => {
  it('refuses a staked duel AT THE DOOR, with a message that says it is not the wallet', async () => {
    render(<LobbyPage onNavigate={navigate} />);

    // Real mode is the default. Enter must NOT navigate.
    // NOTE: the i18n mock returns the KEY, so the accessible names are keys —
    // and they are CONCATENATED across the button's children
    // (`joinDuelBtnprizeLabelenterBtn`), so a substring match is the honest one.
    fireEvent.click(screen.getByRole('button', { name: /enterBtn/ }));

    await waitFor(() => {
      expect(screen.getByText('escrowOfflineTitle')).toBeTruthy();
    });
    expect(navigate).not.toHaveBeenCalled();
    // The copy must not blame the player's wallet — the wallet is fine.
    expect(screen.getByText('escrowOfflineDesc')).toBeTruthy();
  });

  // Free play is NOT asserted here: `e2e/practice-duel.spec.ts` already drives
  // the practice loop end to end against the real stack, and a second, weaker
  // assertion of the same thing would only be a place for the two to disagree.
});
